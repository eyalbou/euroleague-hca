"""Phase G.2 -- render the walkthrough MP4 via ffmpeg.

We pivoted away from Remotion (npm network was unreachable from this shell) to
direct ffmpeg composition. The deliverable is identical: a 1080p 30fps MP4 with
Ken Burns zoom on each frame, crossfade transitions, lower-third captions, and
the voiceover audio overlay.

Strategy:
  1. For each scene, build a short "still video" with zoompan (slow Ken Burns).
  2. Concatenate scenes with xfade transitions.
  3. Overlay lower-third caption text per scene (drawtext timed to scene offset).
  4. Mux with the voiceover audio (`video/public/audio/voiceover.m4a`).

Scene durations are aligned to the narration -- see SCENES below.
Total should match the voiceover length (~165s).
"""
from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("22_render_video")

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "video" / "public" / "frames"
AUDIO = ROOT / "video" / "public" / "audio" / "voiceover.m4a"
OUT_DIR = ROOT / "video" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SCENES_DIR = OUT_DIR / "scenes"
SCENES_DIR.mkdir(parents=True, exist_ok=True)
CAPTIONED_DIR = OUT_DIR / "captioned"
CAPTIONED_DIR.mkdir(parents=True, exist_ok=True)
FINAL = ROOT / "video" / "out" / "walkthrough.mp4"

# macOS font path -- try several possibilities, fall back to PIL default.
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/HelveticaNeue.ttc",
    "/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/HelveticaNeueDeskInterface.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]

FPS = 30
W, H = 1920, 1080
TRANSITION = 0.8  # seconds crossfade between scenes


@dataclass
class Scene:
    frame: str                    # png filename in video/public/frames/
    caption: str                  # lower-third caption (short)
    duration: float               # seconds
    zoom_dir: str = "in"          # "in" or "out"
    focus: tuple[float, float] = (0.5, 0.5)  # x,y in [0,1] to zoom toward


SCENES: list[Scene] = [
    Scene("index.png",
          "EuroLeague Basketball -- 10 seasons, 2,897 games, 1.13M plays",
          13.5, "in", (0.50, 0.35)),
    Scene("index.png",
          "Headline: +3.88 pts home advantage, 1.75x home-win odds",
          13.0, "in", (0.38, 0.42)),
    Scene("dashboard_mechanisms.png",
          "So what drives the home edge? Let's decompose it.",
          7.5, "in", (0.50, 0.50)),
    Scene("referees.png",
          "Hypothesis 1: Referee bias (the NBA finding)",
          10.0, "in", (0.50, 0.30)),
    Scene("referees_funnel.png",
          "Null result: 0 of 61 referees biased after Holm correction",
          16.0, "in", (0.50, 0.35)),
    Scene("transitions_hca.png",
          "Home teams score +0.049 more points per possession",
          17.0, "in", (0.40, 0.45)),
    Scene("transitions_bars.png",
          "The edge shows up in 19 of 19 source actions",
          11.0, "out", (0.50, 0.50)),
    Scene("transitions_bigrams.png",
          "Storylines: momentum is micro, not macro",
          13.0, "in", (0.50, 0.40)),
    Scene("dashboard_covid.png",
          "COVID empty-arena natural experiment: HCA dropped ~1.8 pts",
          18.0, "in", (0.50, 0.45)),
    Scene("dashboard_models.png",
          "Models + mechanism decomposition: 94% of HCA explained",
          12.0, "in", (0.50, 0.45)),
    Scene("index.png",
          "Dashboards, data pipeline, all open-source on GitHub",
          14.0, "out", (0.50, 0.50)),
]

# After summing durations we need to match voiceover (~164s). Sum below:
# 13.5+13+7.5+10+16+17+11+13+18+12+14 = 145s -- leaves ~19s to burn on the
# xfade bleed (each of 10 transitions steals TRANSITION s of the next scene) =
# 10 * 0.8 = 8s. Real output ~137s -- need to stretch. Let me adjust.

# Proper accounting: when xfading, the total = sum(durations) - (n-1)*TRANSITION.
# We want total ~= 164s. So sum(durations) = 164 + 10*0.8 = 172s.
# Current sum = 145s. Need to add 27s across 11 scenes. Distribute evenly.
# I'll apply a multiplier below.


def run(cmd: str, *, check: bool = True) -> subprocess.CompletedProcess:
    log.info("$ %s", cmd if len(cmd) < 200 else cmd[:200] + " ...")
    res = subprocess.run(cmd, shell=True, check=False, capture_output=True, text=True)
    if res.returncode != 0 and check:
        log.error("FFmpeg stderr tail:\n%s", res.stderr[-2000:])
        raise subprocess.CalledProcessError(res.returncode, cmd,
                                            output=res.stdout, stderr=res.stderr)
    return res


def _probe_audio_duration() -> float:
    out = run(f"ffprobe -v error -show_entries format=duration "
              f"-of default=nw=1:nk=1 {shlex.quote(str(AUDIO))}")
    return float(out.stdout.strip())


def _escape_text(text: str) -> str:
    """Escape text for ffmpeg drawtext filter -- colons, backslashes, single quotes."""
    return (text.replace("\\", "\\\\").replace(":", "\\:")
                .replace("'", "\u2019").replace(",", "\\,"))


def _kenburns_filter(scene: Scene, duration: float) -> str:
    """Build a zoompan filter expression for one scene.

    zoompan expects frame-based input. We feed a single still as looped input
    (via -loop 1) and let zoompan produce `d` frames.
    """
    d = int(round(duration * FPS))
    fx, fy = scene.focus
    # Target zoom level at end of scene
    end_zoom = 1.15
    if scene.zoom_dir == "out":
        # Start zoomed in, pan out
        z_expr = f"'if(lte(zoom,1.0),{end_zoom},max(1.0,zoom-0.0008))'"
    else:
        z_expr = f"'min(zoom+0.0008,{end_zoom})'"
    # Center coordinates in the zoompan coordinate space (iw = scaled width etc.)
    x_expr = f"'iw*{fx}-(iw/zoom/2)'"
    y_expr = f"'ih*{fy}-(ih/zoom/2)'"
    return (
        f"zoompan=z={z_expr}:x={x_expr}:y={y_expr}:d={d}:"
        f"s={W}x{H}:fps={FPS}"
    )


def _find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _bake_caption(frame: Path, caption: str, out: Path) -> Path:
    """Load a source frame, draw a lower-third caption bar, save to CAPTIONED_DIR.

    Source frames are 3840x2160 (DPR=2); captions scale proportionally. ffmpeg's
    zoompan will downscale to 1920x1080 afterwards.
    """
    img = Image.open(frame).convert("RGB")
    w, h = img.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    bar_h = int(h * 168 / 1080)
    # Gradient-feel: solid translucent bar
    draw.rectangle((0, h - bar_h, w, h), fill=(0, 0, 0, 180))

    font = _find_font(int(h * 44 / 1080))
    bbox = draw.textbbox((0, 0), caption, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (w - tw) // 2
    y = h - bar_h + (bar_h - th) // 2 - 4
    draw.text((x, y), caption, fill=(255, 255, 255, 255), font=font)

    composed = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    composed.save(out, "PNG", optimize=True)
    return out


def _build_scene(scene: Scene, duration: float, idx: int) -> Path:
    """Bake caption into frame, then ffmpeg zoompan to produce scene clip."""
    out = SCENES_DIR / f"scene_{idx:02d}.mp4"
    frame_path = FRAMES / scene.frame
    assert frame_path.exists(), f"missing frame {frame_path}"

    captioned = CAPTIONED_DIR / f"scene_{idx:02d}_{scene.frame}"
    _bake_caption(frame_path, scene.caption, captioned)

    vf = _kenburns_filter(scene, duration)
    # Feed zoompan exactly one input frame (-frames:v 1) so its `d` parameter
    # governs the entire output duration. Without this, zoompan would emit `d`
    # frames for EACH looped input frame.
    cmd = (
        f"ffmpeg -y -loop 1 -framerate {FPS} "
        f"-i {shlex.quote(str(captioned))} "
        f"-vf {shlex.quote(vf)} "
        f"-frames:v {int(round(duration * FPS))} "
        f"-c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p "
        f"-r {FPS} {shlex.quote(str(out))}"
    )
    run(cmd)
    return out


def _concat_xfade(scene_files: list[Path], durations: list[float]) -> Path:
    """Concatenate scene clips with xfade transitions into a silent video."""
    silent = OUT_DIR / "silent.mp4"
    if len(scene_files) == 1:
        run(f"ffmpeg -y -i {shlex.quote(str(scene_files[0]))} "
            f"-c:v copy {shlex.quote(str(silent))}")
        return silent

    # Build filter_complex: chain xfade between consecutive scenes.
    # offset[i] = sum(durations[0..i]) - (i+1)*TRANSITION  i.e. when xfade from
    # scene i to scene i+1 begins.
    inputs = " ".join(f"-i {shlex.quote(str(f))}" for f in scene_files)
    steps = []
    current = "[0:v]"
    offset = 0.0
    for i in range(1, len(scene_files)):
        offset += durations[i - 1] - TRANSITION
        label = f"v{i}"
        steps.append(
            f"{current}[{i}:v]xfade=transition=fade:"
            f"duration={TRANSITION}:offset={offset:.3f}[{label}]"
        )
        current = f"[{label}]"
    # Total video duration = sum(durations) - (n-1)*TRANSITION
    total = sum(durations) - (len(durations) - 1) * TRANSITION
    filter_complex = ";".join(steps)
    # Final labeled stream is `current`
    cmd = (
        f"ffmpeg -y {inputs} -filter_complex {shlex.quote(filter_complex)} "
        f"-map {shlex.quote(current)} -t {total:.3f} "
        f"-c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p -r {FPS} "
        f"{shlex.quote(str(silent))}"
    )
    run(cmd)
    log.info("silent video length target: %.2fs", total)
    return silent


def _mux_audio(silent: Path, out: Path) -> None:
    cmd = (
        f"ffmpeg -y -i {shlex.quote(str(silent))} "
        f"-i {shlex.quote(str(AUDIO))} "
        f"-c:v copy -c:a aac -b:a 160k -shortest "
        f"-movflags +faststart "
        f"{shlex.quote(str(out))}"
    )
    run(cmd)


def main() -> None:
    audio_dur = _probe_audio_duration()
    log.info("voiceover: %.2fs", audio_dur)

    # Rescale durations so total matches audio (accounting for xfade bleed)
    base = [s.duration for s in SCENES]
    target_total = audio_dur + (len(SCENES) - 1) * TRANSITION
    scale = target_total / sum(base)
    durations = [d * scale for d in base]
    log.info("scale factor on durations: %.3fx (total pre-xfade = %.2fs)",
             scale, sum(durations))

    scene_clips: list[Path] = []
    for idx, (scene, dur) in enumerate(zip(SCENES, durations)):
        clip = _build_scene(scene, dur, idx)
        scene_clips.append(clip)

    silent = _concat_xfade(scene_clips, durations)
    _mux_audio(silent, FINAL)

    # Probe final
    out = run(
        f"ffprobe -v error -show_entries format=duration -show_entries "
        f"stream=width,height,codec_name -of default=nw=1 "
        f"{shlex.quote(str(FINAL))}"
    )
    log.info("FINAL:\n%s", out.stdout)
    log.info("wrote %s (%.1f MB)", FINAL, FINAL.stat().st_size / 1024 / 1024)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "sample":
        # Render just scene 0 at 6s as a smoke test
        _build_scene(SCENES[0], 6.0, 99)
    else:
        main()
