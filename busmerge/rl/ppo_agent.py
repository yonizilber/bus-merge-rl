import torch
import torch.nn as nn
import torch.optim as optim
from torch.distributions import Normal
import os

# --- 1. THE NEURAL NETWORKS ---
class ActorCritic(nn.Module):
    def __init__(self, state_dim, action_dim):
        super(ActorCritic, self).__init__()
        
        # THE ACTOR (The Driver) — shared trunk + two independent heads
        # Bug 5 fix: log_std is now STATE-DEPENDENT so the agent can commit
        # to learned moves instead of permanently jittering (frozen entropy).
        self.actor_trunk = nn.Sequential(
            nn.Linear(state_dim, 64),
            nn.Tanh(),
            nn.Linear(64, 64),
            nn.Tanh(),
        )
        # Mean head: maps trunk features to action mean in [-1, 1]
        self.actor_mean_head = nn.Sequential(
            nn.Linear(64, action_dim),
            nn.Tanh(),
        )
        # Bias the steer output toward "merge by default": tanh(1.0)≈0.76 → steer
        # into lane.  The brain learns to DECREASE steer when unsafe (large crash
        # penalty), which has a direct gradient.  Starting at 0 and learning to
        # increase is much harder (no positive gradient until the first success).
        with torch.no_grad():
            self.actor_mean_head[0].bias[0] = 1.0   # steer: positive → merge intent
        # Log-std head: state-dependent, clamped to keep std in [0.05, 1.65].
        # Bias initialised to -0.7 so initial std ≈ 0.497 (same as before).
        self.actor_log_std_head = nn.Linear(64, action_dim)
        nn.init.zeros_(self.actor_log_std_head.weight)
        nn.init.constant_(self.actor_log_std_head.bias, -0.7)
        
        # THE CRITIC (The Instructor)
        # state_dim Inputs -> 64 Neurons -> 64 Neurons -> 1 Output (Predicted Score)
        self.critic = nn.Sequential(
            nn.Linear(state_dim, 64),
            nn.Tanh(),
            nn.Linear(64, 64),
            nn.Tanh(),
            nn.Linear(64, 1)
        )

    def forward(self, state):
        # 1. Run state through the shared actor trunk
        trunk = self.actor_trunk(state)
        action_mean = self.actor_mean_head(trunk)
        # State-dependent log-std: clamped to [-3, 0.5] so std stays in
        # [0.05, 1.65]. The network can now reduce noise for familiar states
        # and keep exploring in novel ones.
        action_log_std = self.actor_log_std_head(trunk).clamp(-3.0, 0.5)
        action_std = torch.exp(action_log_std)

        # 2. Ask the Critic for the predicted score
        state_value = self.critic(state)

        return action_mean, action_std, state_value


# --- 2. THE PPO MATH ENGINE ---
class PPOAgent:
    def __init__(self, state_dim=11, action_dim=2, filename="checkpoints/ppo_bus_brain.pth", lr=None):
        self.filename = filename
        
        # Hyperparameters (The dials of the AI)
        self.gamma = 0.995      # Raised from 0.99: combined with max_steps=250, terminal reward
                               # at step 250 is worth 5000 × 0.995^250 ≈ 1435 pts (was ~33)
        self.clip_ratio = 0.2   # Forbid learning steps larger than 20%
        self.lr = lr if lr is not None else 5e-5  # default 5e-5; CLI --lr can override
        
        # Initialize the Brain
        self.policy = ActorCritic(state_dim, action_dim)
        self.optimizer = optim.Adam(self.policy.parameters(), lr=self.lr)
        
        # Memory storage for a single "batch" of training
        self.memory = []

    def choose_action(self, state):
        # Convert the standard numpy array into a PyTorch Tensor
        state_tensor = torch.FloatTensor(state).unsqueeze(0)
        
        # We don't want PyTorch calculating calculus while we are just driving, so we use no_grad()
        with torch.no_grad():
            action_mean, action_std, _ = self.policy(state_tensor)
            
        # Create the Bell Curve (Normal Distribution)
        dist = Normal(action_mean, action_std)
        
        # Sample a point from the Bell Curve
        action = dist.sample()

        # Compute log_prob on the RAW (unclamped) sample — BEFORE clamping.
        # If we clamped first, log_prob(1.0) would be the density at 1.0
        # instead of the correct tail probability P(X ≥ 1.0), corrupting
        # the PPO importance ratio for all boundary actions.
        action_logprob = dist.log_prob(action)

        # Now clamp to valid range for the physics engine
        action = torch.clamp(action, -1.0, 1.0)
        # action[0] = steer_intent, action[1] = gas_intent (both in [-1, 1])

        # Return as numpy array (shape [2]) and summed logprob scalar
        return action.squeeze(0).numpy(), action_logprob.sum().item()

    def store_transition(self, state, action, action_logprob, reward, next_state, done):
        # Save this exact 0.1-second memory so we can learn from it later
        self.memory.append((state, action, action_logprob, reward, next_state, done))

    def update(self):
        # PPO update logic lives inline in busmerge/rl/train.py (the training loop).
        # This stub exists for API compatibility only; calling it does nothing.
        # See train.py lines ~377-430 for the actual GAE + clipped surrogate.
        pass

    def save(self):
        # Ensure the checkpoints folder exists
        os.makedirs(os.path.dirname(self.filename), exist_ok=True)
        # Save the exact neural weights to the hard drive
        torch.save(self.policy.state_dict(), self.filename)

    def load(self):
        if os.path.exists(self.filename):
            # Load the neural weights back into the network
            try:
                state_dict = torch.load(self.filename, weights_only=True)
            except TypeError:
                state_dict = torch.load(self.filename)
            try:
                self.policy.load_state_dict(state_dict)
                print("Successfully loaded pre-trained PPO brain!")
            except RuntimeError as e:
                print(f"Checkpoint shape mismatch, starting with fresh weights: {e}")