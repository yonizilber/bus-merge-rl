import tempfile
import streamlit as st
import pandas as pd
import altair as alt
import numpy as np
import re
import time
import json
import os as _os
from busmerge.paths import MODELS_DIR
from busmerge.geometry import compute_sat_overlap_area, rect_corners as _geom_rect_corners
from busmerge import results
from busmerge.geometry import BAY_WALL_Y, bay_outline
from busmerge.graphics.merge_gif import MERGE_X_MAX, MERGE_X_MIN, merge_view_window
from busmerge.invariants import OVERLAP_MIN_AREA_M2, check_invariants
from busmerge.rl.feature_encoding import FEATURE_NAMES, infer_state_dim_from_checkpoint
from busmerge.config import SimConfig
from busmerge.evaluation import TIMELINE_PHASES, classify_outcome, merge_timeline, run_episode
from busmerge.simulation import AnalyticsEngine
from busmerge.rl.queue_analytics import summarize_queue_anomalies, event_window
from busmerge.graphics.renderer import SimulationRenderer


def _smoke_sidecar_path(pth_path: str) -> str:
    return pth_path.replace(".pth", ".smoke.json")


def _read_smoke_sidecar(pth_path: str):
    path = _smoke_sidecar_path(pth_path)
    if not _os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _follower_merge_phase(ft: pd.DataFrame) -> pd.DataFrame:
    """Rows while the bus is actively merging (WAITING_TO_MERGE or MOVING with P < 1)."""
    if ft is None or ft.empty:
        return ft
    active = ft["bus_state"].isin(["WAITING_TO_MERGE", "MOVING"])
    merging = ft["bus_merge_progress"].fillna(0.0) < 0.995
    return ft.loc[active & merging].copy()


def _summarize_follower_brakes(ft: pd.DataFrame) -> dict:
    """Highlight harsh follower deceleration during merge."""
    merge = _follower_merge_phase(ft)
    if merge is None or merge.empty or merge["car_id"].isna().all():
        return {}
    car = merge[merge["car_id"].notna()].copy()
    if car.empty:
        return {}
    hard = car[car["brake_note"].astype(str).str.contains(r"hard|emergency", na=False)]
    holds = car[car["brake_note"].astype(str).str.startswith("stopped", na=False)]
    worst = car.loc[car["accel"].idxmin()] if car["accel"].notna().any() else None
    return {
        "car_id": int(car["car_id"].iloc[0]),
        "merge_frames": len(car),
        "hard_events": len(hard),
        "hold_frames": len(holds),
        "worst_accel": float(worst["accel"]) if worst is not None else None,
        "worst_time": float(worst["time"]) if worst is not None else None,
        "min_speed": float(car["v"].min()),
    }






def _legend_chip(bg: str, fg: str, text: str) -> str:
    return (f'<span style="background-color:{bg};color:{fg};padding:2px 8px;border-radius:4px;'
            f'margin-right:6px;white-space:nowrap">{text}</span>')


def _follower_flag_title(ft) -> str:
    """Title suffix for the follower panel: what is unusual in the merge phase, if anything."""
    if ft is None or ft.empty:
        return ""
    merge = _follower_merge_phase(ft)
    if merge is None or merge.empty:
        return " — nothing unusual"
    notes = merge["brake_note"].astype(str)
    emergency = int(notes.str.startswith("emergency").sum())
    hard = int(notes.str.startswith("hard").sum())
    paradox = int(merge["accel_paradox"].fillna(False).astype(bool).sum()) if "accel_paradox" in merge else 0
    warn = [f"{n} {what}" for n, what in ((emergency, "emergency-brake frame(s)"), (paradox, "accel paradox frame(s)")) if n]
    if warn:
        return " — ⚠️ " + ", ".join(warn) + (f", {hard} hard-brake frame(s)" if hard else "")
    return f" — ℹ️ {hard} hard-brake frame(s)" if hard else " — nothing unusual"


def _governor_shield_log(df):
    """Frames in which the governor vetoed or the shield intervened (None before any run)."""
    if df is None or df.empty:
        return None
    bus = df[df["type"] == "Bus"]
    decided = bus["governor_reason"].astype(str).str.startswith("governor_") | (bus["shield_condition"].astype(str) != "")
    return bus[decided][["time", "merge_progress", "v", "governor_reason", "shield_condition"]].rename(columns={
        "time": "Time (s)", "merge_progress": "Merge P", "v": "Bus vel (m/s)",
        "governor_reason": "Governor reason", "shield_condition": "Shield condition",
    })


def _governor_flag_title(log) -> str:
    if log is None:
        return ""
    if log.empty:
        return " — none"
    is_emergency = log["Shield condition"].astype(str).str.startswith("emergency")
    is_veto = log["Governor reason"].astype(str).str.startswith("governor_")
    emergency, vetoes, others = int(is_emergency.sum()), int(is_veto.sum()), int((~is_emergency & ~is_veto).sum())
    parts = ([f"{emergency} shield emergency frame(s)"] if emergency else []) + ([f"{vetoes} veto(es)"] if vetoes else [])
    if parts:
        return " — ⚠️ " + ", ".join(parts) + (f", {others} other intervention(s)" if others else "")
    return f" — ℹ️ {len(log)} shield intervention(s)"

# --- Page Config ---
st.set_page_config(page_title="Bus Traffic Sim", layout="wide")
st.title("🚌 Traffic Simulation: Behavioral Analysis")
st.caption(
    "For illustration: one run at a time, with the app's own settings (arrivals that find the entry blocked are "
    "lost). The stop-design results come from the experiment (scripts/run_stop_experiment.py), not from this app."
)

# --- INITIALIZE MEMORY ---
# This prevents Streamlit from restarting when you click play
if 'sim_complete' not in st.session_state:
    st.session_state.sim_complete = False
if 'val_demo_df' not in st.session_state:
    st.session_state.val_demo_df = None
if 'val_demo_summary' not in st.session_state:
    st.session_state.val_demo_summary = None
if 'val_demo_walk' not in st.session_state:
    st.session_state.val_demo_walk = None
if 'val_demo_batch_pending' not in st.session_state:
    st.session_state.val_demo_batch_pending = False

# --- Sidebar Controls ---
st.sidebar.header("🧪 Experiment Settings")

# 1. Logic & Scenario
st.sidebar.subheader("Scenario")
_scenario_options = ["A: Bus Stops in Lane", "B: Bus Bay (Layby)"]
_scenario_index = 1  # Scenario B default (trained PPO merge)
scenario_type = st.sidebar.radio(
    "Bus Behavior", _scenario_options, index=_scenario_index,
    help="Trained brains are for Scenario B (bay merge). A is rule-based baseline only.",
)
scenario_code = "A" if "A:" in scenario_type else "B"
if scenario_code == "A":
    st.sidebar.warning("Scenario A ignores the PPO brain for merge — use **B** to test training.")

# 2. Traffic Settings
st.sidebar.subheader("Traffic Conditions")
traffic_density = st.sidebar.slider("Inflow (cars/sec)", 0.1, 1.0, 0.4)
batch_size = st.sidebar.slider("Total Cars to Sim", 20, 100, 50)

# 3. Bus Settings
st.sidebar.subheader("Bus Parameters")
bus_stop_duration = st.sidebar.slider("Stop Duration (s)", 5, 30, 15)
pax_car = st.sidebar.number_input("Pax per Car", 1.0, 5.0, 1.35,
    help="Starting value 1.35: the middle of the Israeli range 1.2 to 1.5 (see the Field data page).")
pax_bus = st.sidebar.number_input("Pax per Bus", 1.0, 100.0, 20.0,
    help="Starting value 20: a rough estimate for an Israeli city bus, not a measurement. Your choice.")

st.sidebar.subheader("Sensor Noise (Robustness Test)")
noise_enabled = st.sidebar.checkbox(
    "Enable Live Sensor Noise", value=False,
    help="Off for first merge test (matches deterministic eval). Enable only for robustness sweeps.",
)
if noise_enabled:
    noise_sigma = st.sidebar.slider("Noise σ (std-dev)", 0.01, 0.50, 0.15, step=0.01,
        help="0.15 = nominal. 0.30 = stress test (not smoke-guaranteed). Smoke test runs at σ=0.")
else:
    noise_sigma = 0.0

use_fixed_seed = st.sidebar.checkbox(
    "Fixed random seed", value=False,
    help="Reproducible run: same seed + same settings = identical result. Off = a different run each time.",
)
run_seed = st.sidebar.number_input("Seed", 0, 1_000_000, 0, disabled=not use_fixed_seed)

# --- Brain picker (default = v13, fine-tuned under the honest steering this app runs) ---
_DEFAULT_BRAIN_BASENAME = "ppo_bus_brain_v13.pth"
_BRAIN_OPTIONS = [
    {
        "path": str(MODELS_DIR / "ppo_bus_brain_v13.pth"),
        "label": "11-feat v13 ★ default (fine-tuned under honest steering)",
        "features": "",
    },
    {
        "path": str(MODELS_DIR / "ppo_bus_brain_v11_engine.pth"),
        "label": "11-feat v11 (relied on the old steering's overshoot; stops half way now)",
        "features": "",
    },
    {
        "path": str(MODELS_DIR / "ppo_bus_brain_exp7satv9_best.pth"),
        "label": "7-feat exp7sat v9 (legacy-env trained)",
        "features": "progress, heading, gap, lat, car_speed, width, rel_speed",
    },
    {
        "path": str(MODELS_DIR / "ppo_bus_brain_exp7satv9.pth"),
        "label": "7-feat exp7sat v9 — latest epoch ckpt",
        "features": "progress, heading, gap, lat, car_speed, width, rel_speed",
    },
    {
        "path": str(MODELS_DIR / "ppo_bus_brain_exp7satv10_best.pth"),
        "label": "11-feat exp7sat v10 — spongy-trained best",
        "features": "progress, heading, gap, lat, car_speed, width, rel_speed, rel_accel, pressure, presence, ttc",
    },
    {
        "path": str(MODELS_DIR / "ppo_bus_brain_exp7satv10.pth"),
        "label": "11-feat exp7sat v10 — spongy-trained latest epoch",
        "features": "progress, heading, gap, lat, car_speed, width, rel_speed, rel_accel, pressure, presence, ttc",
    },
    {
        "path": str(MODELS_DIR / "ppo_bus_brain_exp7sat_best.pth"),
        "label": "7-feat exp7sat v8 — prod-bridge baseline",
        "features": "progress, heading, gap, lat, car_speed, width, rel_speed",
    },
    {
        "path": str(MODELS_DIR / "ppo_bus_brain_exp7sat.pth"),
        "label": "7-feat exp7sat v8 — latest epoch ckpt",
        "features": "progress, heading, gap, lat, car_speed, width, rel_speed",
    },
    {
        "path": str(MODELS_DIR / "ppo_bus_brain_exp4.pth"),
        "label": "4-feat exp4 — steady OU noise",
        "features": "progress, heading, gap, rel_speed",
    },
    {
        "path": str(MODELS_DIR / "ppo_bus_brain_exp7.pth"),
        "label": "7-feat exp7 — no SAT penalty",
        "features": "progress, heading, gap, lat, car_speed, width, rel_speed",
    },
]
_available_brains = [b for b in _BRAIN_OPTIONS if _os.path.isfile(b["path"])]
# The feature count and names come from the checkpoint itself, never from a hand-written label.
for _b in _available_brains:
    _dim = infer_state_dim_from_checkpoint(_b["path"])
    _b["label"] = f"{_dim}-feat " + re.sub(r"^\d+-feat ", "", _b["label"])
    _b["features"] = ", ".join(FEATURE_NAMES[_dim])
# Newest checkpoint mtime first; keep default brain pinned at index 0.
_available_brains.sort(key=lambda b: _os.path.getmtime(b["path"]), reverse=True)
_default_ix = next(
    (i for i, b in enumerate(_available_brains)
     if _os.path.basename(b["path"]) == _DEFAULT_BRAIN_BASENAME),
    0,
)
if _default_ix > 0:
    _available_brains.insert(0, _available_brains.pop(_default_ix))

st.sidebar.subheader("🧠 Brain")
# Off by default — matches exp7sat v7 training. Shield-only safety still active.
enable_governor = st.sidebar.checkbox(
    "Predictive governor",
    value=False,
    help="Off = same as exp7sat training. Enable only for older brains trained with governor on.",
)
if _available_brains:
    _brain_ix = st.sidebar.selectbox(
        "Checkpoint",
        options=range(len(_available_brains)),
        format_func=lambda i: _available_brains[i]["label"],
        index=0,
    )
    selected_brain_path = _available_brains[_brain_ix]["path"]
    _mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(_os.path.getmtime(selected_brain_path)))
    st.sidebar.caption(
        f"`{_os.path.basename(selected_brain_path)}` · {_mtime}\n\n"
        f"Features: {_available_brains[_brain_ix]['features']}"
    )
    if "exp7satv10" in _os.path.basename(selected_brain_path):
        st.sidebar.info(
            "v10 brain: trained with the **spongy danger zone** (graded overlap penalty) "
            "in the gym. This UI judges collisions by the same polygon overlap as v9."
        )

    with st.sidebar.expander("Brain comparison (measured)"):
        _v13 = results.load(results.DEFAULT)["summary"]
        st.markdown(
            "**Setup:** `scripts/verify_brain.py` (the same code as the Run button): Scenario B, "
            "0.4 cars/s, 50 cars, governor off, on seeds that were never used for training or selection. "
            "*Merged* is judged on the traffic only. *Strict* also requires the bus to stay on the road "
            "and out of the opposing lane, with no other physics violation.\n\n"
            + results.brain_table()
            + f"\n\n**Where v13 fails strict:** in {_v13['off_road_pct']:.1f}% of runs the kerb corner at the end "
            "of the exit taper cuts into its side, when it steers out slowly from the far end of the bay. "
            "v9-v11 were trained while the merge steering overshot its target. They ask for a target half "
            "way out of the bay and stop there now (docs/reference/CASE_STUDY_REWARD_HACKING.md). Generated from "
            "results/ (tests/test_published_numbers.py)."
        )

    _smoke = _read_smoke_sidecar(selected_brain_path)
    if _smoke is None:
        st.sidebar.warning("No smoke test on file for this checkpoint.")
    elif "physics_violation_runs" not in _smoke:
        st.sidebar.warning("The smoke result on file predates the physics checks. Re-run it.")
    elif not _smoke.get("passed"):
        _why = f"{_smoke.get('successes', '?')}/{_smoke.get('total', '?')} merges"
        if _smoke.get("physics_violation_runs"):
            _why += (f"; physics violations in {_smoke['physics_violation_runs']} run(s): "
                     + ", ".join(_smoke.get("physics_violation_kinds", [])))
        st.sidebar.error(f"Smoke FAILED ({_why}).")
    else:
        st.sidebar.success(
            f"Smoke passed ({_smoke.get('success_rate', 0) * 100:.0f}% success, σ=0)."
        )

    if st.sidebar.button("Validate brain (smoke test)", help="10 seeds, Scenario B, using the traffic settings above, no noise."):
        with st.spinner("Running production smoke test…"):
            from busmerge.rl.smoke_test_production import run_smoke_test
            _ok = run_smoke_test(
                ckpt_path=selected_brain_path,
                n_seeds=10,
                max_steps=3000,
                min_success_rate=0.90,
                max_avg_merge_s=30.0,
                max_wait_s=45.0,
                scenario="B",
                write_sidecar=True,
                governor_disabled=not enable_governor,
                traffic_rate=traffic_density,
                total_cars=batch_size,
            )
        st.session_state.smoke_result = _ok
        st.rerun()

    _smoke_result = st.session_state.pop("smoke_result", None)
    if _smoke_result is not None:
        (st.sidebar.success if _smoke_result else st.sidebar.error)(
            "Smoke test passed" if _smoke_result else "Smoke test failed — see terminal")

    with st.sidebar.expander("Training validation demo (10×3)", expanded=False):
        from busmerge.rl.validation_constants import TRAINING_VALIDATION_SEEDS
        st.caption(
            "Runs the **same 10 held-out seeds × 3 episodes** as end-of-training validation "
            f"({', '.join(str(s) for s in TRAINING_VALIDATION_SEEDS)}). "
            "**Visual walkthrough** shows **gym exact** + **Streamlit** GIFs side by side; "
            "**Table only** runs all 60 episodes in ~30 s."
        )
        _val_eps = st.number_input("Episodes per seed", 1, 5, 3, key="val_demo_eps")
        _b1, _b2 = st.columns(2)
        with _b1:
            if st.button("▶ Visual walkthrough", key="val_demo_walk_start", type="primary"):
                _q = [(s, e) for s in TRAINING_VALIDATION_SEEDS for e in range(int(_val_eps))]
                st.session_state.val_demo_walk = {
                    "queue": _q,
                    "index": 0,
                    "rows": [],
                    "need_run": True,
                    "episodes_per_seed": int(_val_eps),
                    "current_train": None,
                    "current_stream": None,
                    "current_df": None,
                    "current_gym_df": None,
                }
                st.session_state.val_demo_batch_pending = False
                st.rerun()
        with _b2:
            if st.button("Table only (fast)", key="val_demo_batch"):
                st.session_state.val_demo_batch_pending = True
                st.session_state.val_demo_walk = None
else:
    st.sidebar.error(f"No checkpoints found in {MODELS_DIR}")
    selected_brain_path = None

st.sidebar.subheader("📊 Diagnostics (after run)")
st.sidebar.caption("Off by default — skip heavy post-run work for faster dashboard load.")
show_merge_zone_animation = st.sidebar.checkbox(
    "Merge-zone animation",
    value=True,
    help="Top-down frames and GIF of the merge zone (renders every frame; the slowest part of a run).",
)
show_queue_anomalies = st.sidebar.checkbox(
    "Queue anomalies",
    value=False,
    help="Overtake/bypass detector on full frame history.",
)
show_follower_telemetry = st.sidebar.checkbox(
    "Car behind bus (merge telemetry)",
    value=True,
    help="Frame-by-frame trace of the car behind the bus from dwell through merge completion. "
         "Flags hard/emergency stops and hold-lock events.",
)
show_governor_shield_log = st.sidebar.checkbox(
    "Governor / shield decisions",
    value=True,
    help="Every frame where the predictive governor vetoed the bus's action or the reactive "
         "safety shield modified it, with the reason string for each. Empty = no run yet.",
)
show_frame_inspector = st.sidebar.checkbox(
    "Single-frame inspector",
    value=False,
    help="Step through merge-zone frames one at a time.",
)
show_sat_validation = st.sidebar.checkbox(
    "SAT collision validation",
    value=False,
    help="Corner-point overlay to verify polygon collision math.",
)
show_bus_entry_telemetry = st.sidebar.checkbox(
    "Bus entry telemetry",
    value=False,
    help="Bus decel/bay table: speed, heading, steer.",
)

# --- Simulation Execution ---
config = SimConfig(
    total_cars_to_spawn=batch_size, 
    traffic_rate=traffic_density,
    pax_per_car=pax_car,
    pax_per_bus=pax_bus,
    bus_dwell_time=bus_stop_duration,
)

# --- Training validation demo (10 held-out seeds × N episodes) ---
if st.session_state.get("val_demo_batch_pending") and selected_brain_path:
    from busmerge.rl.validation_demo import run_validation_comparison, summarize_comparison
    from busmerge.rl.validation_constants import TRAINING_VALIDATION_SEEDS

    _eps = int(st.session_state.get("val_demo_eps", 3))
    _prog = st.progress(0, text="Starting validation comparison…")
    _status = st.empty()

    def _on_prog(done, total, msg):
        _prog.progress(min(done / max(total, 1), 1.0), text=msg)
        _status.caption(f"{done}/{total} — {msg}")

    with st.spinner(f"Running {len(TRAINING_VALIDATION_SEEDS)}×{_eps} training + Streamlit episodes…"):
        _vdf = run_validation_comparison(
            selected_brain_path,
            seeds=TRAINING_VALIDATION_SEEDS,
            episodes_per_seed=_eps,
            governor_disabled=not enable_governor,
            streamlit_config=config,
            include_streamlit=True,
            progress_callback=_on_prog,
        )
    st.session_state.val_demo_df = _vdf
    st.session_state.val_demo_summary = summarize_comparison(_vdf)
    st.session_state.val_demo_batch_pending = False
    _prog.empty()
    _status.empty()
    st.rerun()

_walk = st.session_state.get("val_demo_walk")
if _walk and selected_brain_path:
    from busmerge.rl.validation_demo import run_episode_pair, summarize_comparison
    from busmerge.rl.validation_constants import TRAINING_VALIDATION_SEEDS
    from busmerge.graphics.merge_gif import build_merge_gif

    _queue = _walk["queue"]
    _idx = int(_walk["index"])
    _total = len(_queue)

    if _idx < _total and _walk.get("need_run"):
        _seed, _ep = _queue[_idx]
        with st.spinner(f"Running seed {_seed}, episode {_ep}…"):
            _tr, _st, _df, _gdf, _, _ = run_episode_pair(
                selected_brain_path,
                _seed,
                _ep,
                int(_walk["episodes_per_seed"]),
                config,
                governor_disabled=not enable_governor,
            )
        _walk["rows"] = _walk.get("rows", []) + [_tr, _st]
        _walk["current_train"] = _tr
        _walk["current_stream"] = _st
        _walk["current_df"] = _df
        _walk["current_gym_df"] = _gdf
        _walk["need_run"] = False
        st.session_state.val_demo_walk = _walk

    if _idx < _total:
        st.divider()
        _seed, _ep = _queue[_idx]
        st.subheader(f"🔬 Validation walkthrough — episode {_idx + 1} / {_total}")
        st.caption(f"Secret seed **{_seed}**, episode **{_ep}** (RNG = seed+ep, same as training)")

        _tr = _walk.get("current_train") or {}
        _st_row = _walk.get("current_stream") or {}
        _c1, _c2, _c3 = st.columns(3)
        with _c1:
            _to = _tr.get("outcome", "—")
            st.metric("Training gym", _to, delta=None)
            st.caption(
                f"scenario **{_tr.get('scenario_name', '?')}** (roll {_tr.get('scenario_roll', 0):.3f}) · "
                f"initial gap **{_tr.get('initial_gap_m', '?')} m** · "
                f"ended {_tr.get('merge_progress', 0):.0%}"
            )
        with _c2:
            _so = _st_row.get("outcome", "—")
            st.metric("Streamlit engine", _so, delta=None)
            st.caption(f"merge {_st_row.get('merge_s', '—')} s · {_st_row.get('traffic_note', '')}")
        with _c3:
            if _to != _so:
                st.warning("**Disagree** — the two engines judged this episode differently")
            else:
                st.success("Both agree")

        _gdf_ep = _walk.get("current_gym_df")
        if _gdf_ep is not None and not _gdf_ep.empty:
            st.markdown("#### 🎯 Gym exact replay")
            st.caption(
                "Bus **already in the bay** at t=0. Cars placed **instantly** behind it — "
                "no approach, no dwell. Orange car = overlap / negative gap at that frame. "
                f"Episode lasted **{_tr.get('steps', '?')}** gym steps "
                f"({_tr.get('steps', 0) * 0.1:.1f} s) before `{_to}`."
            )
            _gym_gif = build_merge_gif(_gdf_ep, config, fps=2, max_frames=60)
            if _gym_gif:
                st.image(_gym_gif, width="stretch")
            _t0 = _gdf_ep[_gdf_ep["time"] == 0.0]
            if not _t0.empty:
                _bus = _t0[_t0["type"] == "Bus"]
                _cars = _t0[_t0["type"] == "Car"].sort_values("x", ascending=False)
                if not _bus.empty and not _cars.empty:
                    _bx = float(_bus.iloc[0]["x"])
                    _nearest = _cars.iloc[0]
                    st.info(
                        f"At **t=0** (before brain acts): nearest car **#{int(_nearest['id'])}** "
                        f"at x={_nearest['x']:.1f} m, v={_nearest['v']:.1f} m/s — "
                        f"longitudinal gap to bus ≈ **{_tr.get('initial_gap_m', '?')} m**. "
                        "If gap is negative, SAT crash can fire on the first merge step."
                    )

        _df_ep = _walk.get("current_df")
        if _df_ep is not None and not _df_ep.empty:
            st.markdown("#### 🚌 Streamlit production replay")
            st.caption(
                "Full Scenario B: bus drives from x=0, dwells in bay ~15 s, traffic spawns continuously — "
                "then merges. Same RNG seed+episode, **different timeline**."
            )
            _gif = build_merge_gif(_df_ep, config, fps=5)
            if _gif:
                st.image(_gif, width="stretch")
            else:
                st.info("No merge-zone frames to animate for this episode.")
        else:
            st.info("Waiting for episode data…")

        _nc1, _nc2, _nc3 = st.columns(3)
        with _nc1:
            if st.button("Next episode →", key="val_demo_next", type="primary"):
                _walk["index"] = _idx + 1
                _walk["need_run"] = True
                st.session_state.val_demo_walk = _walk
                st.rerun()
        with _nc2:
            if st.button("Skip to summary", key="val_demo_skip"):
                st.session_state.val_demo_df = pd.DataFrame(_walk.get("rows", []))
                st.session_state.val_demo_summary = summarize_comparison(st.session_state.val_demo_df)
                st.session_state.val_demo_walk = None
                st.rerun()
        with _nc3:
            if st.button("Stop walkthrough", key="val_demo_stop"):
                st.session_state.val_demo_walk = None
                st.rerun()
    elif _idx >= _total and _walk:
        st.session_state.val_demo_df = pd.DataFrame(_walk.get("rows", []))
        st.session_state.val_demo_summary = summarize_comparison(st.session_state.val_demo_df)
        st.session_state.val_demo_walk = None
        st.rerun()

if st.session_state.val_demo_df is not None and st.session_state.get("val_demo_walk") is None:
    _vsum = st.session_state.val_demo_summary or {}
    st.divider()
    st.subheader("🔬 Training validation demo — 10 held-out seeds × 3 episodes")
    st.markdown(
        "This is the **same test** printed at the end of PPO training. "
        "Left column = **training gym** (`BusMergeEnv`, static queue at reset). "
        "Right = **Streamlit engine** (continuous traffic — what you use in the UI)."
    )
    _c1, _c2, _c3 = st.columns(3)
    _train_stats = _vsum.get("training (BusMergeEnv)", {})
    _stream_stats = _vsum.get("streamlit (SimulationEngine)", {})
    with _c1:
        st.metric("Training gym", _train_stats.get("score", "—"))
        st.caption(f"crash {_train_stats.get('crashes', 0)} · timeout {_train_stats.get('timeouts', 0)}")
    with _c2:
        st.metric("Streamlit engine", _stream_stats.get("score", "—"))
        st.caption(f"crash {_stream_stats.get('crashes', 0)} · timeout {_stream_stats.get('timeouts', 0)}")
    with _c3:
        if _train_stats and _stream_stats:
            st.metric(
                "Extra Streamlit wins",
                f"+{int(_stream_stats.get('successes', 0)) - int(_train_stats.get('successes', 0))}",
            )

    _vdf = st.session_state.val_demo_df.copy()
    _pivot = _vdf.pivot_table(
        index=["seed", "episode"],
        columns="engine",
        values="outcome",
        aggfunc="first",
    ).reset_index()
    _pivot.columns.name = None
    if len(_pivot.columns) >= 4:
        _train_col = [c for c in _pivot.columns if "training" in str(c).lower()][0]
        _stream_col = [c for c in _pivot.columns if "streamlit" in str(c).lower()][0]
        _pivot["disagree"] = _pivot[_train_col] != _pivot[_stream_col]
        _disagree_n = int(_pivot["disagree"].sum())
        if _disagree_n:
            st.info(
                f"**{_disagree_n}** episode(s) where training and Streamlit disagree — "
                "usually training **crash** at progress≈0 while Streamlit **success**."
            )

    st.dataframe(
        _vdf.rename(columns={
            "engine": "Engine",
            "seed": "Seed",
            "episode": "Ep",
            "outcome": "Outcome",
            "merge_progress": "Max progress",
            "steps": "Steps",
            "merge_s": "Merge (s)",
            "traffic_note": "Traffic model",
        }),
        width="stretch",
        height=420,
    )
    with st.expander("Pivot: training vs Streamlit per seed×episode"):
        st.dataframe(_pivot, width="stretch")

    _crash_train = _vdf[
        (_vdf["engine"].str.contains("training"))
        & (_vdf["outcome"] == "crash")
        & (_vdf["merge_progress"] < 0.15)
    ]
    if not _crash_train.empty:
        st.caption(
            f"Training crashes at low progress (&lt;15%): **{len(_crash_train)}** episodes — "
            "typically a spawn overlap at merge start."
        )
    if st.button("Clear validation results", key="val_demo_clear"):
        st.session_state.val_demo_df = None
        st.session_state.val_demo_summary = None
        st.rerun()

if st.button("Run Simulation"):
    with st.spinner(f"Simulating {batch_size} cars..."):
        progress_bar = st.progress(0)
        sim = run_episode(
            scenario_code,
            config,
            selected_brain_path,
            governor_disabled=not enable_governor,
            noise_sigma=noise_sigma,
            seed=int(run_seed) if use_fixed_seed else None,
            on_progress=lambda s: progress_bar.progress(min(s.cars_finished_count / (batch_size + 1), 1.0)),
        )
        progress_bar.empty()
        
        # Remember which brain was used
        st.session_state.active_brain = getattr(sim, "active_brain_path", selected_brain_path or "default")
        st.session_state.feature_dim = getattr(sim, "feature_dim", 4)
        st.session_state.run_scenario = scenario_code
        st.session_state.df = sim.get_results()
        st.session_state.follower_df = sim.get_follower_trace()
        st.session_state.sim_complete = True
        st.session_state.run_config = config
        st.session_state.run_id = st.session_state.get("run_id", 0) + 1

# --- DASHBOARD & ANIMATION (Runs outside the Run button) ---
if st.session_state.sim_complete:
    # Show the settings the run was made with, not whatever the sidebar says now.
    config = st.session_state.get("run_config", config)
    scenario_code = st.session_state.get("run_scenario", scenario_code)
    df = st.session_state.df
    _brain_name = _os.path.basename(st.session_state.get("active_brain", "unknown"))
    _fd = st.session_state.get("feature_dim", 4)
    st.info(f"🧠 Active brain: **{_brain_name}** ({_fd}-feature)")

    _outcome, _meta = classify_outcome(df)
    if _outcome == "merged":
        _sc = st.session_state.get("run_scenario", "?")
        st.success(f"Bus merged in **{_meta['merge_s']:.1f}s** after boarding ended (Scenario {_sc}).")
        _tl = merge_timeline(df)
        if _tl:
            st.caption("Where the time went, from the end of boarding to fully merged:")
            st.table(pd.DataFrame(
                [{"Phase": label, "Seconds": _tl[key]} for key, label in TIMELINE_PHASES]
                + [{"Phase": "**Total** (fully centred in lane)", "Seconds": _tl["total_s"]},
                   {"Phase": "of which standing still", "Seconds": _tl["standstill_s"]}]
            ).set_index("Phase"))
        _fb = _summarize_follower_brakes(st.session_state.get("follower_df"))
        if _fb:
            if _fb["hard_events"] > 0:
                st.warning(
                    f"Car **#{_fb['car_id']}** behind the bus had **{_fb['hard_events']}** hard/emergency "
                    f"brake frame(s) during merge — peak decel **{_fb['worst_accel']:.1f} m/s²** "
                    f"at t={_fb['worst_time']:.1f}s "
                    "(typical car ABS limit ≈ 8–10 m/s²). See telemetry below."
                )
            elif _fb["hold_frames"] > 0:
                st.info(
                    f"Car **#{_fb['car_id']}** held position for **{_fb['hold_frames']}** frames during merge "
                    f"(min speed {_fb['min_speed']:.2f} m/s). See telemetry below."
                )
    # Accel paradox: logged acceleration does not explain the speed change (should never happen)
    _fdf = st.session_state.get("follower_df")
    if _fdf is not None and len(_fdf) > 0:
        if "accel_paradox" in _fdf.columns:
            _par_frames = _fdf[_fdf["accel_paradox"] == True]
            if len(_par_frames) > 0:
                _par_car = int(_par_frames.iloc[0].get("car_id", -1))
                _par_t = float(_par_frames.iloc[0]["time"])
                st.sidebar.warning(
                    f"[Accel Paradox] Implied Δv/dt ≠ logged accel — "
                    f"Car #{_par_car} at t={_par_t:.1f}s  "
                    "(the logged acceleration does not explain the speed change)"
                )

    if _outcome == "stuck_waiting":
        _mp = _meta.get("max_progress")
        _extra = f" (max progress { _mp:.0%})" if _mp is not None else ""
        st.error(
            f"Bus never completed the merge into the lane{_extra} — waited ~{_meta.get('wait_s', 0):.0f}s."
        )
    elif _outcome == "off_road":
        st.error(
            f"Bus left the road (kerb or bay wall) at t={_meta.get('first_off_road_s', float('nan')):.1f}s, "
            f"for {_meta.get('off_road_frames', 0)} frames — a failure, even if it then merged."
        )
    elif _outcome == "over_centre_line":
        st.error(
            f"Bus crossed the centre line into the opposing lane at "
            f"t={_meta.get('first_over_centre_s', float('nan')):.1f}s — a failure, even if it then merged."
        )
    elif _outcome == "collision":
        st.error("Physical collision in merge zone — brain failed safety.")
    elif _outcome == "never_waited":
        st.warning("Bus never entered WAITING_TO_MERGE — check scenario B and bay setup.")
    elif _outcome == "no_merge":
        st.warning("Bus moved without a clear merge-from-wait sequence.")

    # --- Physics checks: impossible moments are shown, never hidden ---
    _inv = check_invariants(df)
    if _inv.total == 0:
        st.success("Physics checks: no physically impossible moment in this run.")
    else:
        _parts = ", ".join(f"{k.replace('_', ' ')} ×{n}" for k, n in _inv.counts.items() if n)
        st.error(
            f"Physics checks failed: {_parts}. Worst braking {_inv.worst_decel:.1f} m/s² "
            "(physical limit 9). The first example of each kind is listed below."
        )
        with st.expander("First example of each physics violation"):
            st.json(_inv.examples)
    if any(_inv.notes.values()):
        st.info(
            "Reported, not a failure: a car's body crossed "
            + ", ".join(f"{ {'car_off_road': 'the kerb', 'car_over_centre_line': 'the centre line'}[k]} in {n} frames"
                        for k, n in _inv.notes.items() if n)
            + " (cars drift in their lane and move over for the bus)."
        )

    # --- Analytics ---
    analytics = AnalyticsEngine(df, config)
    kpis = analytics.compute_kpis()
    
    # --- 1. DATA PREPARATION (Smart Sampling) ---
    st.subheader("Traffic Visualization")
    st.caption(
        "Bus inner color during merge: **gold** = lane partly open (cars can pass); "
        "**red** = lane blocked. Cars use continuous yield — cruise when bus progress is low "
        "and gap > 50 m; brake when merge is material and gap is small. "
        "Hover bus: **Δx** should stay ~v×0.1 m; large negative **Δx** = backward snap. "
        "Trajectory uses **every 0.1 s frame** (no subsampling)."
    )

    # A. Strict Sorting
    df = df.sort_values(by=['id', 'time'])

    # Trajectory chart: full frame history (no random subsample — avoids false chords/gaps).
    chart_data = df.copy()

    def _chart_segment_key(row):
        """Line continuity: cars keep one segment while driving; bus splits on state machine."""
        st = str(row.get("state", ""))
        if row["type"] == "Bus":
            return st
        if "Squeezing" in st or "Reacting" in st or st == "Cruising":
            return "CarDriving"
        return st

    chart_data["segment_key"] = chart_data.apply(_chart_segment_key, axis=1)
    chart_data["segment_id"] = chart_data.groupby("id")["segment_key"].transform(
        lambda s: (s != s.shift()).cumsum()
    )
    
    # C. COLOR LOGIC (Refined)
    def get_inner_color(row):
        state_str = str(row['state'])

        # BUS LOGIC
        if row['type'] == 'Bus':
            if "SHOCKED" in state_str: return 'black'   
            if state_str == 'IN_BAY': return '#333333'  
            
            if state_str == 'WAITING_TO_MERGE': 
                presence = float(row['presence'])
                
                # DYNAMIC COLOR CALCULATION (Matches Physics)
                lane_width = 3.5
                safety_gap = 0.5
                bus_width = 2.5
                car_width = 1.9
                
                space_left = lane_width - (presence * bus_width)
                space_needed = car_width + safety_gap
                
                if space_left >= space_needed:
                    return '#FFD700' # Gold (Creeping, car can still pass)
                else:
                    return '#FF0000' # Red (Lane Blocked!)
                    
            return '#ffb3b3' # FIX: Light red instead of white for MOVING   
        
        # CAR LOGIC
        else:
            if state_str == 'Squeezing!': return 'purple' 
            if "Reacting" in state_str: return '#FF69B4' # Hot Pink
            return '#aec7e8'     # Light Blue

    chart_data['inner_color'] = chart_data.apply(get_inner_color, axis=1)

    # --- 2. VISUALIZATION (Clean & Direct) ---
    hover = alt.selection_point(on='mouseover', fields=['id'], empty=False)
    click = alt.selection_point(fields=['id'], toggle=True)

    base = alt.Chart(chart_data).encode(
        x=alt.X('time', title='Time (s)'),
        y=alt.Y('x', title='Position (m)'),
        detail=['id', 'segment_id'], # <--- FIX: Added segment_id here!
        tooltip=[
            alt.Tooltip('id', title='Vehicle ID'),
            alt.Tooltip('type', title='Type'),
            alt.Tooltip('class', title='Class'),
            alt.Tooltip('x', format='.1f', title='Absolute Pos (m)'),
            alt.Tooltip('dx', format='+.3f', title='Δx (m/frame)'),
            alt.Tooltip('yield_eff', format='.2f', title='Merge yield Y'),
            alt.Tooltip('v', format='.1f', title='Speed (m/s)'),
            alt.Tooltip('state', title='Status'),
            alt.Tooltip('presence', format='.2f', title='Own Solidity'),
            alt.Tooltip('front_gap', format='.2f', title='Front-Rear Gap (m)'),
            alt.Tooltip('lateral_gap', format='.2f', title='Lateral Gap (m)'),
            alt.Tooltip('physical_collision', title='⚠️ Physical Collision (both gaps <0)'),
            alt.Tooltip('leader_info', title='Following'),
            alt.Tooltip('leader_id', title='Leader ID'),
            alt.Tooltip('queue_rank', title='Queue rank (0=front)'),
            alt.Tooltip('bus_visibility', title='Perceives Bus As')
        ]
    )

    outer_line = base.mark_line().encode(
        color=alt.Color('type', scale=alt.Scale(domain=['Car', 'Bus'], range=['#1f77b4', '#d62728']), legend=None),
        opacity=alt.condition(click, alt.value(0.8), alt.value(0.1)),
        strokeWidth=alt.condition(hover, alt.value(7), alt.value(4))
    ).add_params(hover, click)

    inner_line = base.mark_line().encode(
        color=alt.Color('inner_color', scale=None, legend=None),
        opacity=alt.condition(click, alt.value(1.0), alt.value(0.1)),
        strokeWidth=alt.condition(hover, alt.value(3), alt.value(2))
    )

    chart = (outer_line + inner_line).properties(
        width=800, height=500,
        title=f"Scenario {scenario_code}: Trajectories (Hover = Thicker, Shift+Click = Isolate)"
    ).interactive()

    st.altair_chart(chart, width="stretch")

    # --- Queue / bypass anomaly detector (optional — skips O(n²) scan when off) ---
    if show_queue_anomalies:
        _qa = summarize_queue_anomalies(df, chart_data)
        _merge_done = _qa["merge_end_t"]
        _post_ot = _qa["post_merge_overtakes"]
        with st.expander("🔍 Queue anomalies — overtakes & bypass (full physics data)", expanded=bool(len(_post_ot))):
            st.markdown(
                "Space–time **line crossings** mean one vehicle's front bumper passed another's "
                "(longitudinal overtake). This uses **every 0.1 s frame**, not the subsampled chart above. "
                "Post-merge events are after the bus first reaches **MOVING**."
            )
            if _merge_done is not None:
                st.caption(f"Bus merge complete (MOVING) at **t ≈ {_merge_done:.1f} s**")
            else:
                st.caption("Bus merge end time not detected in this run.")

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Post-merge overtakes", len(_post_ot))
            c2.metric("All overtakes", len(_qa["overtakes"]))
            c3.metric("Negative front gaps", len(_qa["negative_gaps"]))
            c4.metric("|Δx| ≥ 3 m jumps", len(_qa["position_jumps"]))

            if _post_ot.empty and _qa["overtakes"].empty:
                st.success("No longitudinal overtakes detected in full frame history.")
            else:
                _show = _post_ot if not _post_ot.empty else _qa["overtakes"]
                _show = _show.rename(columns={
                    "time": "Time (s)",
                    "x_cross": "Cross x (m)",
                    "passer_id": "Passer ID",
                    "passed_id": "Passed ID",
                    "passer_type": "Passer",
                    "passed_type": "Passed",
                    "passer_v": "Passer v (m/s)",
                    "passed_v": "Passed v (m/s)",
                    "delta_x_before_m": "Was behind by (m)",
                })
                st.dataframe(_show, width="stretch", hide_index=True)

                if not _post_ot.empty:
                    _opts = [
                        f"t={r['time']:.1f}s  {r['passer_type']} {int(r['passer_id'])} passes "
                        f"{r['passed_type']} {int(r['passed_id'])} @ x≈{r['x_cross']:.0f}m"
                        for _, r in _post_ot.iterrows()
                    ]
                    _pick = st.selectbox("Inspect event (±3 s window)", _opts, key="queue_event_pick")
                    _idx = _opts.index(_pick)
                    _row = _post_ot.iloc[_idx]
                    _t0 = float(_row["time"])
                    _ids = [int(_row["passer_id"]), int(_row["passed_id"])]
                    if int(_row["passed_id"]) == 999 or int(_row["passer_id"]) == 999:
                        _ids.append(999)
                    _win = event_window(df, _t0, _ids, half_width_s=3.0)
                    if "leader_id" not in _win.columns and "leader_info" in _win.columns:
                        from busmerge.rl.queue_analytics import parse_leader_id
                        _win = _win.copy()
                        _win["leader_id"] = _win["leader_info"].map(parse_leader_id)
                    st.caption(f"Frame-by-frame for IDs {_ids} around t = {_t0:.1f} s")
                    st.dataframe(
                        _win.style.format({
                            "time": "{:.2f}",
                            "x": "{:.2f}",
                            "dx": "{:+.3f}",
                            "v": "{:.2f}",
                            "front_gap": "{:.2f}",
                            "lateral_gap": "{:.2f}",
                            "total_lat": "{:.3f}",
                            "yield_eff": "{:.3f}",
                        }, na_rep="—"),
                        width="stretch",
                        height=320,
                    )
                    _mini = df[(df["id"].isin(_ids)) & (df["time"] >= _t0 - 5) & (df["time"] <= _t0 + 5)]
                    if not _mini.empty:
                        _cross = alt.Chart(_mini).mark_line(point=True).encode(
                            x=alt.X("time", title="Time (s)"),
                            y=alt.Y("x", title="Position (m)"),
                            color=alt.Color("id:N", title="ID"),
                            tooltip=["time", "id", "type", "x", "dx", "v", "leader_info", "front_gap", "queue_rank"],
                        ).properties(title="Full-rate trajectories ±5 s (no subsampling)", height=280)
                        st.altair_chart(_cross, width="stretch")

            if not _qa["negative_gaps"].empty:
                st.warning("Negative front-gap frames (longitudinal overlap recorded in telemetry)")
                st.dataframe(_qa["negative_gaps"].head(30), width="stretch")

            if not _qa["position_jumps"].empty:
                st.warning("Large single-frame Δx (physics teleport candidates)")
                st.dataframe(_qa["position_jumps"].head(20), width="stretch")

            _art = _qa.get("chart_artifact_crossings", pd.DataFrame())
            if not _art.empty:
                st.info(
                    f"**{len(_art)} apparent crossing(s) in the subsampled chart only** — "
                    "these are chord artifacts from 20% frame sampling, not real overtakes. "
                    "Compare with **Post-merge overtakes = 0** above."
                )
                st.dataframe(
                    _art.rename(columns={
                        "time": "Chart time (s)",
                        "passer_id": "Passer ID",
                        "passed_id": "Passed ID",
                        "x_cross": "Apparent cross x (m)",
                    }),
                    width="stretch",
                    hide_index=True,
                )

    # --- Merge Zone 2D View (Scenario B only — no bay merge in A) ---
    _run_scenario = st.session_state.get("run_scenario", scenario_code)
    if _run_scenario == "B":
        st.divider()
        st.subheader("📐 Merge Zone: Top-Down 2D View")
        st.caption(
            "X = road position (m). Y = lateral offset from lane centre (m). "
            "Vehicle rectangles are **rotated by their real heading angle**. "
            "**Overlapping polygons = physical collision.**"
        )

        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import io

        # ── Geometry constants (must match simulation.py / vehicle.py) ───────────
        BUS_STOP_X    = config.bus_stop_position   # 300.0
        LANE_W        = 3.5
        # The bay is drawn from busmerge.geometry, the same outline the physics checks use.
        BAY_OUTLINE   = bay_outline()

        merge_df_all = df[(df['x'] >= MERGE_X_MIN) & (df['x'] <= MERGE_X_MAX)].copy()

        if not show_merge_zone_animation:
            st.caption("Merge-zone animation is off (sidebar, Diagnostics).")
        elif merge_df_all.empty:
            st.info("No vehicles entered the merge zone in this run.")
        else:
            # ── Per-frame lateral centre ─────────────────────────────────────────
            def lateral_y(row):
                if row['type'] == 'Bus':
                    # Use total_lat (= lateral_offset + lane_drift) — consistent with GIF renderer.
                    total_lat = row.get('total_lat', float('nan'))
                    if not pd.isna(total_lat):
                        return float(total_lat)
                    return float(row.get('lateral_offset', 0.0))
                total_lat = row.get('total_lat', 0.0)
                return float(total_lat) if not pd.isna(total_lat) else 0.0

            merge_df_all = merge_df_all.copy()
            merge_df_all['y_centre']  = merge_df_all.apply(lateral_y, axis=1)
            merge_df_all['half_w']    = merge_df_all['width']  / 2.0
            merge_df_all['half_l']    = merge_df_all['length'] / 2.0
            # x is the front bumper (physics convention); polygons are built around the centre.
            merge_df_all['x_centre']  = merge_df_all['x'] - merge_df_all['half_l']
            merge_df_all['heading']   = merge_df_all['heading_deg'].fillna(0.0) if 'heading_deg' in merge_df_all.columns else 0.0
            if 'heading_anomaly' not in merge_df_all.columns:
                merge_df_all['heading_anomaly'] = False

            # ── Rotated-polygon collision detection (per frame) ──────────────────
            def rect_corners(cx, cy, half_l, half_w, angle_deg):
                return _geom_rect_corners(cx, cy, half_l, half_w, np.radians(angle_deg))

            collision_times = set()
            for t_val, grp in merge_df_all.groupby('time'):
                bus_rows = grp[grp['type'] == 'Bus']
                car_rows = grp[grp['type'] == 'Car']
                if bus_rows.empty or car_rows.empty:
                    continue
                br = bus_rows.iloc[0]
                bus_poly = rect_corners(br['x_centre'], br['y_centre'], br['half_l'], br['half_w'],
                                        float(br['heading']) if not pd.isna(br['heading']) else 0.0)
                for _, cr in car_rows.iterrows():
                    car_poly = rect_corners(cr['x_centre'], cr['y_centre'], cr['half_l'], cr['half_w'],
                                            float(cr['heading']) if not pd.isna(cr['heading']) else 0.0)
                    if compute_sat_overlap_area(bus_poly, car_poly) > OVERLAP_MIN_AREA_M2:
                        collision_times.add(t_val)
                        break

            merge_df_all['collision_frame'] = merge_df_all['time'].isin(collision_times)

            n_collision_times = len(collision_times)
            if n_collision_times:
                st.warning(f"⚠️ {n_collision_times} collision frame(s) detected — orange cars below.")
            else:
                st.success("✅ No physical overlaps detected in merge zone.")

            # ── Pre-render all frames to PNG bytes (fast scrubbing) ─────────────
            def _draw_bay(ax):
                """Draw road + accurate trapezoidal bus bay."""
                # Main traffic lane
                ax.axhspan(-LANE_W/2, LANE_W/2, color='#555555', zorder=0)
                ax.axhline( LANE_W/2,   color='white', ls='--', lw=1.5, zorder=1)
                ax.axhline(-LANE_W/2,   color='white', ls='-',  lw=2.0, zorder=1)

                # Bus bay (entry taper, flat section, exit taper), closed along the kerb
                from matplotlib.patches import Polygon as MplPolygon
                ax.add_patch(MplPolygon(BAY_OUTLINE, closed=True, facecolor='#444444',
                                        edgecolor='white', linewidth=0.8, zorder=0))

                # Bus stop marker
                ax.axvline(BUS_STOP_X, color='yellow', ls=':', lw=1.2, alpha=0.7, zorder=1)
                ax.text(BUS_STOP_X, BAY_WALL_Y + 0.2, 'STOP', color='yellow',
                        ha='center', va='bottom', fontsize=7, zorder=2)

            def _render_frame(t_val):
                frame = merge_df_all[merge_df_all['time'] == t_val]
                fig, ax = plt.subplots(figsize=(16, 5))
                _draw_bay(ax)

                is_collision = t_val in collision_times
                for _, row in frame.iterrows():
                    angle = float(row['heading']) if not pd.isna(row['heading']) else 0.0
                    color = ('#e74c3c' if row['type'] == 'Bus'
                             else ('#FF8C00' if row['collision_frame'] else '#3498db'))
                    corners = rect_corners(row['x_centre'], row['y_centre'],
                                           row['half_l'], row['half_w'], angle)
                    poly_patch = mpatches.Polygon(corners, closed=True,
                                                  facecolor=color, edgecolor='white',
                                                  linewidth=1.4, zorder=5)
                    ax.add_patch(poly_patch)
                    if row['type'] == 'Bus':
                        hdg = float(row['heading']) if not pd.isna(row['heading']) else 0.0
                        anomaly = bool(row.get('heading_anomaly', False))
                        label = f"{'⚠ ' if anomaly else ''}BUS\n{row.get('v', 0.0):.1f}m/s\n{hdg:+.0f}°"
                        # Red edge border when a heading-snap anomaly has been detected
                        if anomaly:
                            poly_patch.set_edgecolor('yellow')
                            poly_patch.set_linewidth(3.0)
                    else:
                        label = f"{int(row['id'])}\n{row.get('v', 0.0):.1f}m/s"
                    ax.text(row['x_centre'], row['y_centre'], label,
                            color='white', ha='center', va='center',
                            fontsize=6.5, zorder=6)

                ax.set_xlim(MERGE_X_MIN, MERGE_X_MAX)
                ax.set_ylim(BAY_WALL_Y - 0.4, LANE_W / 2 + 0.5)
                ax.set_xlabel("Road position (m)")
                ax.set_ylabel("Lateral (m)")
                ax.set_title(
                    f"Merge Zone Top-Down  |  t = {t_val:.1f} s"
                    + ("  ⚠️ COLLISION FRAME" if is_collision else ""),
                    fontsize=11, color='red' if is_collision else 'black'
                )
                ax.set_aspect('equal')
                ax.legend(handles=[
                    mpatches.Patch(color='#e74c3c', label='Bus'),
                    mpatches.Patch(color='#3498db', label='Car'),
                    mpatches.Patch(color='#FF8C00', label='Collision'),
                ], loc='upper right', fontsize=9)
                ax.grid(axis='x', color='white', alpha=0.15, zorder=0)

                buf = io.BytesIO()
                fig.savefig(buf, format='png', dpi=110, bbox_inches='tight')
                plt.close(fig)
                buf.seek(0)
                return buf.read()

            all_times_full = sorted(merge_df_all['time'].unique())

            # ── Render window: from shortly before boarding ends until the bus has left the view ──
            _window = merge_view_window(df)
            t_window_start, t_window_end = _window if _window else (all_times_full[0], all_times_full[-1])
            all_times = [t for t in all_times_full if t_window_start <= t <= t_window_end]
            if not all_times:
                all_times = all_times_full

            # Cache rendered frames in session state keyed by run hash
            run_hash = str(st.session_state.get("run_id", 0))
            cache_key = f"merge_frames_{run_hash}"
            if cache_key not in st.session_state:
                with st.spinner(f"Pre-rendering {len(all_times)} merge frames…"):
                    st.session_state[cache_key] = {t: _render_frame(t) for t in all_times}
            frame_images = st.session_state[cache_key]

            # ── Speed-controllable animated GIF ──────────────────────────────────
            # Encoding is fast (PIL only, no ffmpeg). Cached per fps value.
            fps_options = [1, 2, 3, 5, 8, 10, 15, 20]
            fps = st.select_slider(
                "Playback speed (frames/sec)",
                options=fps_options,
                value=5,
                key=f"fps_{run_hash}",
                format_func=lambda v: f"{v} fps  ({len(all_times)/v:.0f} s video)"
            )
            gif_key = f"merge_gif_{run_hash}_{fps}"
            if gif_key not in st.session_state:
                from PIL import Image as _PILImg
                with st.spinner("Encoding animation…"):
                    pil_frames = [_PILImg.open(io.BytesIO(frame_images[t])).convert('RGBA')
                                  for t in all_times]
                    gif_buf = io.BytesIO()
                    pil_frames[0].save(
                        gif_buf, format='GIF', save_all=True,
                        append_images=pil_frames[1:],
                        duration=int(1000 / fps),
                        loop=0, optimize=False,
                    )
                    st.session_state[gif_key] = gif_buf.getvalue()

            st.image(st.session_state[gif_key], width="stretch")
            st.caption(
                f"Window: t = {all_times[0]:.1f} s → {all_times[-1]:.1f} s  |  "
                f"{len(all_times)} frames  |  1 frame = {df['time'].diff().median():.2g} s simulation time"
            )

            # ── Single-frame inspector (optional) ─────────────────────────────────
            if show_frame_inspector:
                with st.expander("🔍 Single-frame inspector (step through frames)", expanded=True):
                    slider_key = f"tslider_{run_hash}"
                    if slider_key not in st.session_state:
                        first_ct = min((t for t in collision_times if t in all_times), default=all_times[0])
                        st.session_state[slider_key] = first_ct
                    if st.session_state[slider_key] not in all_times:
                        st.session_state[slider_key] = all_times[0]

                    def _cur_idx():
                        return all_times.index(st.session_state[slider_key])

                    c1, c2, c3, c4 = st.columns([1, 1, 1, 6])
                    with c3:
                        n_step = st.number_input("Step n", 1, 50, 5, key=f"nstep_{run_hash}")
                    with c1:
                        if st.button("◀ −n", key=f"prev_{run_hash}"):
                            st.session_state[slider_key] = all_times[max(0, _cur_idx() - int(n_step))]
                            st.rerun()
                    with c2:
                        if st.button("▶ +n", key=f"next_{run_hash}"):
                            st.session_state[slider_key] = all_times[min(len(all_times)-1, _cur_idx() + int(n_step))]
                            st.rerun()
                    with c4:
                        st.select_slider("Time (s)", options=all_times,
                                         format_func=lambda t: f"{t:.1f} s", key=slider_key)
                    st.image(frame_images[st.session_state[slider_key]], width="stretch")

            # ── SAT collision debug (optional) ────────────────────────────────────
            if show_sat_validation:
                with st.expander("🔬 SAT collision validation — corner-point overlay", expanded=True):
                    st.markdown(
                        "**SAT (Separating Axis Theorem) proof of correctness**: for two convex polygons, "
                        "if no separating axis exists among the 8 edge-normals (4 per polygon), the polygons "
                        "overlap — this is a necessary AND sufficient condition (zero false positives/negatives). "
                        "The yellow dots below are the computed corner positions. "
                        "Verify they sit exactly at the physical edges of each vehicle."
                    )
                    debug_t = st.select_slider(
                        "Frame to inspect", options=all_times,
                        format_func=lambda t: f"{t:.1f} s",
                        key=f"sat_debug_{run_hash}"
                    )
                    frame_dbg = merge_df_all[merge_df_all['time'] == debug_t]
                    fig_d, ax_d = plt.subplots(figsize=(16, 5))
                    _draw_bay(ax_d)
                    for _, row in frame_dbg.iterrows():
                        angle = float(row['heading']) if not pd.isna(row['heading']) else 0.0
                        color = '#e74c3c' if row['type'] == 'Bus' else '#3498db'
                        corners = rect_corners(row['x_centre'], row['y_centre'],
                                               row['half_l'], row['half_w'], angle)
                        ax_d.add_patch(mpatches.Polygon(corners, closed=True,
                                       facecolor=color, edgecolor='white',
                                       linewidth=1.2, alpha=0.55, zorder=5))
                        ax_d.scatter(corners[:,0], corners[:,1],
                                     c='yellow', s=30, zorder=8)
                        arrow_len = row['half_l'] * 0.7
                        ax_d.annotate('', xy=(row['x_centre'] + arrow_len * np.cos(np.radians(angle)),
                                              row['y_centre'] + arrow_len * np.sin(np.radians(angle))),
                                      xytext=(row['x_centre'], row['y_centre']),
                                      arrowprops=dict(arrowstyle='->', color='lime', lw=1.8), zorder=9)
                        ax_d.text(row['x_centre'], row['y_centre'],
                                  f"{int(row['id'])} {angle:.1f}°",
                                  color='white', ha='center', va='center', fontsize=7, zorder=10)
                    ax_d.set_xlim(MERGE_X_MIN, MERGE_X_MAX)
                    ax_d.set_ylim(BAY_WALL_Y - 0.4, LANE_W / 2 + 0.5)
                    ax_d.set_aspect('equal')
                    ax_d.set_title(f"Corner verification  t = {debug_t:.1f} s  |  "
                                   f"{'⚠️ SAT: COLLISION' if debug_t in collision_times else '✅ SAT: clear'}")
                    st.pyplot(fig_d, width="stretch")
                    plt.close(fig_d)

            # ── Bus Merge Telemetry table ─────────────────────────────────────────
            with st.expander("📋 Bus Merge Telemetry (frame-by-frame from first movement)", expanded=False):
                _bus_wt = merge_df_all[
                    (merge_df_all['type'] == 'Bus') &
                    (merge_df_all['state'] == 'WAITING_TO_MERGE')
                ].copy().sort_values('time')
                _bus_wt_moving = _bus_wt[_bus_wt['v'] > 0.1]
                if _bus_wt_moving.empty:
                    st.info("Bus never moved during WAITING_TO_MERGE in this recording window.")
                else:
                    _t_first_move = _bus_wt_moving['time'].min()
                    # Start 5 frames (0.5 s) before first movement so the
                    # 0 → speed transition is visible in the table.
                    _N_BEFORE = 5
                    _all_wt_times = sorted(_bus_wt['time'].unique())
                    _idx_first = _all_wt_times.index(_t_first_move) if _t_first_move in _all_wt_times else 0
                    _t_table_start = _all_wt_times[max(0, _idx_first - _N_BEFORE)]
                    _after_start = _bus_wt[_bus_wt['time'] >= _t_table_start].copy()
                    _fully_merged = _after_start[_after_start['merge_progress'] >= 0.99]
                    if not _fully_merged.empty:
                        _t_end = _fully_merged['time'].min()
                        _merge_telem = _after_start[_after_start['time'] <= _t_end].copy()
                    else:
                        _merge_telem = _after_start.copy()  # merge not yet complete — show all
                    _dt = 0.1  # simulation step
                    _n_frames = len(_merge_telem)
                    _t_last = float(_merge_telem['time'].max()) if not _merge_telem.empty else _t_first_move
                    _merge_telem['accel'] = _merge_telem['v'].diff() / _dt
                    _merge_telem['accel'] = _merge_telem['accel'].fillna(0.0)
                    _merge_telem = _merge_telem.rename(columns={
                        'time':           'Time (s)',
                        'x':              'Pos X (m)',
                        'v':              'Speed (m/s)',
                        'accel':          'Accel (m/s²)',
                        'lateral_offset': 'Lateral Y (m)',
                        'heading_deg':    'Heading (°)',
                        'steer_angle_deg':'Steer (°)',
                        'merge_progress': 'Progress',
                        'bus_control':    'Control',
                    })[['Time (s)', 'Pos X (m)', 'Speed (m/s)', 'Accel (m/s²)',
                         'Lateral Y (m)', 'Heading (°)', 'Steer (°)', 'Progress', 'Control']]
                    _merge_telem = _merge_telem.reset_index(drop=True)
                    st.caption(f"{_n_frames} frames — t = {_t_table_start:.1f} s "
                               f"(5 frames before first movement at {_t_first_move:.1f} s) "
                               f"→ t = {_t_last:.1f} s (merge complete)")
                    st.dataframe(
                        _merge_telem.style.format({
                            'Time (s)':     '{:.2f}',
                            'Pos X (m)':    '{:.2f}',
                            'Speed (m/s)':  '{:.3f}',
                            'Accel (m/s²)': '{:.3f}',
                            'Lateral Y (m)':'{:.4f}',
                            'Heading (°)':  '{:.2f}',
                            'Steer (°)':    '{:.2f}',
                            'Progress':     '{:.3f}',
                        }).background_gradient(subset=['Accel (m/s²)'], cmap='RdYlGn', vmin=-3, vmax=3),
                        width="stretch",
                        height=420,
                    )

            # ── Bus Entry Telemetry (optional) ────────────────────────────────────
            if show_bus_entry_telemetry:
                with st.expander("📊 Bus Entry Telemetry (frame-by-frame)", expanded=True):
                    st.markdown(
                        "Frame-by-frame bus state from **first DECELERATING step** through "
                        "**bay stop**.  Use this to diagnose steering oscillation and "
                        "confirm the parking crawl behaviour."
                    )
                    bus_telem = merge_df_all[merge_df_all['type'] == 'Bus'][
                        ['time', 'v', 'lateral_offset', 'heading_deg', 'steer_angle_deg', 'state']
                    ].copy()
                    entry_states = {'DECELERATING', 'IN_BAY'}
                    bus_telem = bus_telem[bus_telem['state'].isin(entry_states)].copy()
                    bus_telem = bus_telem.rename(columns={
                        'time':           'Time (s)',
                        'v':              'Vel (m/s)',
                        'lateral_offset': 'Actual Y (m)',
                        'heading_deg':    'Heading (°)',
                        'steer_angle_deg':'Steer (°)',
                        'state':          'State',
                    })
                    bus_telem = bus_telem.reset_index(drop=True)
                    if bus_telem.empty:
                        st.info("No DECELERATING/IN_BAY frames in the recorded window.")
                    else:
                        st.dataframe(
                            bus_telem.style.format({
                                'Time (s)':    '{:.2f}',
                                'Vel (m/s)':   '{:.3f}',
                                'Actual Y (m)':'{:.4f}',
                                'Heading (°)': '{:.4f}',
                                'Steer (°)':   '{:.4f}',
                            }),
                            width="stretch",
                            height=400,
                        )

    # --- 3. Results ---
    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Time", f"{df['time'].max():.1f} s")
    c2.metric("Avg Speed", f"{kpis['avg_person_speed']:.1f} km/h")
    c3.metric("Throughput", f"{kpis['throughput_people']} pax")

    # --- Diagnostics under the merge-zone view (collapsed; the title flags anything unusual) ---
    # --- Car Following Bus Telemetry (optional) ---
    if show_follower_telemetry:
        _follower_df = st.session_state.get("follower_df")
        with st.expander("🚗 Car Behind Bus — Merge Telemetry" + _follower_flag_title(_follower_df), expanded=False):
            st.markdown(
                "Row colours: "
                + _legend_chip("#6b2b2b", "#ffe8e8", "emergency braking (≤ -5 m/s²)")
                + _legend_chip("#6b4a22", "#fff0dd", "hard braking (≤ -3.5 m/s²)")
                + _legend_chip("#2a3f5c", "#dce8f5", "stopped")
                + _legend_chip("#2b4c6f", "#e8f1fa", "accel paradox (should never happen)"),
                unsafe_allow_html=True,
            )
            st.markdown(
                "One row every **0.1 s** from **IN_BAY** through **merge complete** (progress → 100%). "
                "Tracks the same car behind the bus (sticky ID). "
                "**Car accel** is the physics deceleration (m/s²) — use this to judge brake severity. "
                "**Car Δv** is speed change this step; divide by 0.1 s to get implied m/s² (can spike when follower ID switches). "
                "**Brake note:** `comfort` / `hard` / `emergency` = braking class, `stopped` = at rest. "
                "Every speed change comes from the logged acceleration (no corrections exist)."
            )
            if _follower_df is None or _follower_df.empty:
                st.info("No follower trace — use Scenario B and run a simulation.")
            else:
                ft = _follower_df.copy()
                merge_ft = _follower_merge_phase(ft)
                _fb = _summarize_follower_brakes(ft)
                st.caption(
                    f"{len(ft)} total frames  |  "
                    f"{len(merge_ft)} merge-phase frames  |  "
                    f"t = {ft['time'].min():.1f} → {ft['time'].max():.1f} s"
                )
                if _fb:
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Follower ID", f"#{_fb['car_id']}")
                    c2.metric("Hard brake frames", _fb["hard_events"])
                    c3.metric("Hold-lock frames", _fb["hold_frames"])
                    c4.metric(
                        "Peak decel (accel)",
                        f"{_fb['worst_accel']:.1f} m/s²" if _fb["worst_accel"] is not None else "—",
                    )

                view_mode = st.radio(
                    "Show frames",
                    ["Merge phase only", "Full trace (dwell + merge)"],
                    horizontal=True,
                    key="follower_view_mode",
                )
                display_ft = merge_ft if view_mode == "Merge phase only" else ft

                ft = display_ft.rename(columns={
                    "frame": "Frame",
                    "time": "Time (s)",
                    "dt": "Δt (s)",
                    "bus_state": "Bus state",
                    "bus_x": "Bus pos (m)",
                    "bus_dx": "Bus Δx (m)",
                    "bus_v": "Bus vel (m/s)",
                    "bus_max_front": "Bus max front (m)",
                    "bus_merge_progress": "Bus merge P",
                    "car_id": "Car ID",
                    "x": "Car pos (m)",
                    "v": "Car vel (m/s)",
                    "accel": "Car accel (m/s²)",
                    "car_dx": "Car Δx (m)",
                    "car_dv": "Car Δv (m/s)",
                    "comfort_brake": "Comfort brake (m/s²)",
                    "reaction_timer": "Reaction (s)",
                    "brake_note": "Brake note",
                    "follower_switched": "Follower switched",
                    "front_gap": "Front gap (m)",
                    "rear_gap_to_bus": "Rear gap (m)",
                    "max_front_allowed": "Car max front (m)",
                    "yield_eff": "Yield Y",
                    "yield_raw": "Yield Raw",
                    "leader_id": "Leader ID",
                    "bus_is_leader": "Bus is leader",
                    "leader_presence": "Leader presence",
                    "leader_info": "Sees (leader)",
                    "bus_visibility": "Bus presence seen",
                    "car_state": "Car state",
                    "accel_paradox": "Accel paradox",
                    "blinker_presence": "Blinker pres.",
                    "signaling_merge": "Signaling",
                })
                _lead_cols = [
                    "Frame", "Time (s)", "Bus state", "Bus merge P",
                    "Car ID", "Car vel (m/s)", "Car accel (m/s²)", "Car Δv (m/s)",
                    "Brake note", "Rear gap (m)", "Yield Y", "Yield Raw",
                    "Bus is leader", "Accel paradox",
                    "Blinker pres.", "Signaling",
                ]
                _rest = [c for c in ft.columns if c not in _lead_cols]
                ft = ft[[c for c in _lead_cols if c in ft.columns] + _rest]

                def _highlight_brake_rows(row):
                    """Readable highlights on dark Streamlit theme (avoid pale yellow)."""
                    note = str(row.get("Brake note", "") or "")
                    if row.get("Accel paradox"):
                        # Slate blue — readable white text, not yellow-on-yellow
                        return ["background-color: #2b4c6f; color: #e8f1fa"] * len(row)
                    if note == "emergency" or note.startswith("emergency"):
                        return ["background-color: #6b2b2b; color: #ffe8e8"] * len(row)
                    if note == "hard" or note.startswith("hard"):
                        return ["background-color: #6b4a22; color: #fff0dd"] * len(row)
                    if note == "stopped":
                        return ["background-color: #2a3f5c; color: #dce8f5"] * len(row)
                    return [""] * len(row)

                st.dataframe(
                    ft.style.format({
                        "Frame": "{:.0f}",
                        "Time (s)": "{:.2f}",
                        "Δt (s)": "{:.1f}",
                        "Bus pos (m)": "{:.3f}",
                        "Bus Δx (m)": "{:+.3f}",
                        "Bus vel (m/s)": "{:.3f}",
                        "Bus max front (m)": "{:.3f}",
                        "Car pos (m)": "{:.3f}",
                        "Car Δx (m)": "{:+.3f}",
                        "Car vel (m/s)": "{:.3f}",
                        "Car accel (m/s²)": "{:.3f}",
                        "Car Δv (m/s)": "{:+.3f}",
                        "Comfort brake (m/s²)": "{:.2f}",
                        "Reaction (s)": "{:.2f}",
                        "Front gap (m)": "{:.2f}",
                        "Rear gap (m)": "{:.2f}",
                        "Car max front (m)": "{:.3f}",
                        "Yield Y": "{:.3f}",
                        "Hold X (m)": "{:.3f}",
                        "Leader presence": "{:.3f}",
                        "Bus merge P": "{:.3f}",
                    }, na_rep="—").apply(_highlight_brake_rows, axis=1),
                    width="stretch",
                    height=450,
                )
                _plot = ft[ft["Car ID"].notna()].copy()
                if not _plot.empty:
                    st.caption("Follower speed & acceleration during merge (orange = hard, red = emergency)")
                    _speed_chart = _plot[["Time (s)", "Car vel (m/s)", "Car accel (m/s²)"]].set_index("Time (s)")
                    st.line_chart(_speed_chart, height=200)
                    _pos_chart = _plot[
                        ["Time (s)", "Bus pos (m)", "Car pos (m)", "Rear gap (m)", "Yield Y"]
                    ].set_index("Time (s)")
                    st.caption("Position & gap (watch Car Δx for backward snaps)")
                    st.line_chart(_pos_chart, height=200)

    # --- Governor / Shield decision log (optional) ---
    if show_governor_shield_log:
        _gov_df = st.session_state.get("df")
        _gov_log = _governor_shield_log(_gov_df)
        with st.expander("🚦 Governor / Shield Decisions" + _governor_flag_title(_gov_log), expanded=False):
            st.markdown(
                "Frames in which the **predictive governor** vetoed the brain's action (it is off by default, "
                "and then never vetoes) or the **reactive safety shield** changed it (always on, in training too), "
                "with the reason for each. Only while the bus is `WAITING_TO_MERGE`.\n\n"
                "Row colours: "
                + _legend_chip("#6b2b2b", "#ffe8e8", "shield emergency (emergency_stop / emergency_forward)")
                + _legend_chip("#6b5a22", "#fff3d6", "other shield intervention")
                + _legend_chip("#4b2b6b", "#f0e6ff", "governor veto"),
                unsafe_allow_html=True,
            )
            if _gov_log is None:
                st.info("No run yet — click Run Simulation.")
            elif _gov_log.empty:
                st.success("No governor vetoes or shield interventions this run.")
            else:
                _waiting = int(((_gov_df["type"] == "Bus") & (_gov_df["state"] == "WAITING_TO_MERGE")).sum())
                st.caption(f"{len(_gov_log)} frame(s) with a governor/shield decision, out of {_waiting} "
                           "WAITING_TO_MERGE frames.")

                def _colour_decision(row):
                    shield, gov = str(row["Shield condition"]), str(row["Governor reason"])
                    if shield.startswith("emergency"):
                        return ["background-color: #6b2b2b; color: #ffe8e8"] * len(row)
                    if gov.startswith("governor_"):
                        return ["background-color: #4b2b6b; color: #f0e6ff"] * len(row)
                    return ["background-color: #6b5a22; color: #fff3d6"] * len(row)

                st.dataframe(
                    _gov_log.style.format({"Time (s)": "{:.2f}", "Merge P": "{:.3f}", "Bus vel (m/s)": "{:.3f}"})
                    .apply(_colour_decision, axis=1),
                    width="stretch",
                    hide_index=True,
                )

    # --- 4. 2D ANIMATION VISUALIZER ---
    st.divider()
    st.subheader("🎬 Live 2D Playback")
    
    # We add columns to put the Play button and Download button side-by-side
    btn_col1, btn_col2 = st.columns([1, 4])
    
    with btn_col1:
        play_btn = st.button("Render Smooth Video")
        
    if play_btn:
        with st.spinner("Rendering Video (Takes ~5 seconds)..."):
            import matplotlib.pyplot as plt
            import matplotlib.animation as animation
            
            renderer = SimulationRenderer(df, config)
            # Take every 4th frame. 
            time_steps = sorted(df['time'].unique())[::4] 
            
            fig = plt.figure(figsize=(12, 3))
            ax = fig.add_axes([0, 0, 1, 1]) 
            
            def update(t):
                renderer.draw_frame(ax, t)
                return ax,
                
            anim = animation.FuncAnimation(fig, update, frames=time_steps, blit=False)
            
            # SLOWED DOWN: fps changed from 10 to 5 for half-speed playback
            with tempfile.TemporaryDirectory() as _tmp:
                _gif_path = _os.path.join(_tmp, "animation.gif")
                anim.save(_gif_path, writer='pillow', fps=5)
                with open(_gif_path, "rb") as _f:
                    _gif_bytes = _f.read()
            plt.close(fig)

            st.image(_gif_bytes, width="stretch")
            btn_col2.download_button(
                label="💾 Download GIF",
                data=_gif_bytes,
                file_name="bus_simulation.gif",
                mime="image/gif",
            )
