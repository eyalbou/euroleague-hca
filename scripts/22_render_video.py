"""Phase G.2 (rewrite) -- render the walkthrough MP4 with per-scene
narration synchronization, Track-A / Track-B chapter cards, and
color-coded lower-third captions.

Pipeline:
  1. Split narration into per-scene lines
  2. Generate a per-scene audio clip (macOS `say` -> m4a)
  3. Probe each clip's exact duration
  4. Render a per-scene video still (Ken Burns zoompan + fade-in/out +
     baked caption), duration matched to the audio clip
  5. Hard-concat all audio clips into one m4a
  6. Hard-concat all video clips (no xfade -- we use within-clip fades)
  7. Mux final MP4 (1080p, 30fps, yuv420p, AAC 64kbps)

Output: euroleague-hca/video/out/walkthrough.mp4

The monolithic narration.txt remains the source of truth for
credits / README copy, but the scene order below is authoritative
for the rendered video.
"""
from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("22_render_video")

ROOT = Path(__file__).resolve().parents[1]
FRAMES = ROOT / "video" / "public" / "frames"
AUDIO_DIR = ROOT / "video" / "public" / "audio"
OUT_DIR = ROOT / "video" / "out"
SCENES_DIR = OUT_DIR / "scenes"
CAPTIONED_DIR = OUT_DIR / "captioned"
AUDIO_CLIPS_DIR = AUDIO_DIR / "scenes"
for d in (OUT_DIR, SCENES_DIR, CAPTIONED_DIR, AUDIO_CLIPS_DIR):
    d.mkdir(parents=True, exist_ok=True)
FINAL = OUT_DIR / "walkthrough.mp4"

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/HelveticaNeue.ttc",
    "/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/HelveticaNeueDeskInterface.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]

FPS = 30
W, H = 1920, 1080
TTS_VOICE = "Samantha"
TTS_RATE = 175
TAIL_PAD = 0.45


TRACK_A = (60, 207, 142)
TRACK_B = (110, 176, 255)
NEUTRAL = (200, 200, 200)


@dataclass
class Scene:
    frame: str
    narration: str
    caption: str
    zoom_dir: str = "in"
    focus: tuple[float, float] = (0.5, 0.5)
    track: str = "neutral"
    silent_pad: float = 0.0


SCENES: list[Scene] = [
    Scene(frame="index.png",
          narration="Do EuroLeague home teams win more? And if they do, why?",
          caption="Do home teams really win more?",
          zoom_dir="in", focus=(0.50, 0.35), track="neutral"),
    Scene(frame="index.png",
          narration=("I analyzed eleven seasons of EuroLeague basketball. "
                     "Thirty-two hundred games. One point seven million "
                     "play-by-play events. All of it running locally, "
                     "in Cursor, on my laptop."),
          caption="11 seasons  -  3,278 games  -  1.72M plays",
          zoom_dir="in", focus=(0.30, 0.45), track="neutral"),
    Scene(frame="index.png",
          narration=("One dataset. Two investigations. Track A -- "
                     "why home wins. Track B -- how possessions chain. "
                     "Let's start with Track A."),
          caption="Two tracks, one dataset",
          zoom_dir="out", focus=(0.50, 0.60), track="neutral"),

    Scene(frame="chapter_track_a.png",
          narration="",
          caption="",
          zoom_dir="in", focus=(0.50, 0.50), track="A", silent_pad=2.2),

    Scene(frame="dashboard_overview.png",
          narration=("The headline. EuroLeague home teams win one point "
                     "seven five times more often than road teams. Plus "
                     "three point seven three points per game, on average. "
                     "An eleven-season mean, stable across seasons."),
          caption="+3.73 pts  -  1.75x home odds  -  n=3,278",
          zoom_dir="in", focus=(0.42, 0.40), track="A"),
    Scene(frame="referees.png",
          narration=("So the question becomes: why? The old answer, from "
                     "N B A research, is referee bias. Home refs whistle "
                     "fewer fouls on home players. I tested it for Europe. "
                     "Every referee with at least thirty games "
                     "over eleven seasons."),
          caption="Hypothesis 1: referee bias (Scorecasting, NBA)",
          zoom_dir="in", focus=(0.50, 0.35), track="A"),
    Scene(frame="referees_funnel.png",
          narration=("After Holm correction for simultaneous "
                     "tests, the number of statistically biased referees "
                     "came out to zero. European officiating, within our "
                     "statistical power, is neutral. That hypothesis is dead."),
          caption="0 biased refs (Holm-corrected) - hypothesis dead",
          zoom_dir="in", focus=(0.50, 0.40), track="A"),
    Scene(frame="dashboard_mechanisms.png",
          narration=("So what is driving the home edge? I decomposed every "
                     "box-score mechanism. Shooting efficiency. Turnovers. "
                     "Free-throw rate. Pace."),
          caption="Mechanism decomposition: eFG, TOV, FTR, pace",
          zoom_dir="in", focus=(0.50, 0.45), track="A"),
    Scene(frame="dashboard_covid.png",
          narration=("Then, COVID became a natural experiment nobody could "
                     "run on purpose. Games played in empty arenas dropped "
                     "home advantage by almost two points per game. When fans "
                     "came back, so did the edge. Crowd presence matters -- "
                     "but it is one layer, not the whole story."),
          caption="COVID natural experiment: HCA fell ~1.8 pts",
          zoom_dir="in", focus=(0.50, 0.45), track="A"),
    Scene(frame="dashboard_models.png",
          narration=("The full model explains ninety four percent of home "
                     "advantage from measurable, in-game mechanism."),
          caption="Models: 94% of HCA explained by measurable mechanism",
          zoom_dir="in", focus=(0.50, 0.45), track="A"),

    Scene(frame="dashboard_overview.png",
          narration=("Okay. Mechanism. But where does that plus three point "
                     "seven three actually live, play by play? For that: "
                     "Track B."),
          caption="Where does +3.73 live, play by play?",
          zoom_dir="out", focus=(0.50, 0.50), track="neutral"),

    Scene(frame="chapter_track_b.png",
          narration="",
          caption="",
          zoom_dir="in", focus=(0.50, 0.50), track="B", silent_pad=2.2),

    Scene(frame="transitions_bars.png",
          narration=("After every action on the floor, what comes next? "
                     "First-order Markov chains, computed over one point "
                     "three million in-play events."),
          caption="First-order Markov chains  -  1.29M in-play events",
          zoom_dir="in", focus=(0.40, 0.40), track="B"),
    Scene(frame="transitions_hca.png",
          narration=("Then I added a home-versus-road lens on top. Home teams "
                     "score zero point zero four nine more points per "
                     "possession than road teams. That tiny per-possession "
                     "edge, times roughly seventy four possessions a team "
                     "per game, reproduces almost all of the three point "
                     "seven three."),
          caption="+0.049 PPP  x  ~74 poss/team/game  =  +3.73 pts",
          zoom_dir="in", focus=(0.45, 0.45), track="B"),
    Scene(frame="transitions_hca.png",
          narration=("Every action. Eighteen of eighteen possession starters. "
                     "The home edge is not one big thing. It is a thousand "
                     "small things."),
          caption="18 of 18 source actions favor home",
          zoom_dir="in", focus=(0.55, 0.55), track="B"),
    Scene(frame="transitions_bigrams.png",
          narration=("Two-step chains -- what I call Storylines. After a "
                     "home-team defensive rebound, the next three events "
                     "cascade, slightly, in the home team's favor. "
                     "Momentum exists. It is just micro."),
          caption="Storylines: momentum is real, but micro",
          zoom_dir="in", focus=(0.50, 0.40), track="B"),

    Scene(frame="rebound_rates.png",
          narration=("Two more things fell out of this analysis. After a "
                     "three-point miss, offensive-rebound odds are measurably "
                     "higher than after a two-point miss. After a terminal "
                     "free-throw miss, different again. Three shooting "
                     "regimes, three rebound dynamics -- with confidence "
                     "intervals on every number."),
          caption="Rebound rates by miss type  -  3pt vs 2pt vs FT",
          zoom_dir="in", focus=(0.50, 0.40), track="B"),
    Scene(frame="anomalies.png",
          narration=("And a catalog of ten basketball anomalies: the "
                     "first-score effect, tied-at-half home-win rates, "
                     "quarter-by-quarter asymmetry -- each with a "
                     "basketball-analyst interpretation."),
          caption="Ten basketball anomalies  -  analyst reads",
          zoom_dir="in", focus=(0.50, 0.35), track="A"),

    Scene(frame="explorer.png",
          narration=("Everything is filterable. Pick any teams. Any seasons. "
                     "The numbers recompute in your browser."),
          caption="Multi-select filters  -  live in browser",
          zoom_dir="in", focus=(0.45, 0.40), track="neutral"),
    Scene(frame="index.png",
          narration=("The dashboards are live, the code is open, the link "
                     "is in the description. Thanks for watching."),
          caption="eyalbou.github.io/euroleague-hca",
          zoom_dir="out", focus=(0.50, 0.40), track="neutral"),
]


def run(cmd: str, *, check: bool = True) -> subprocess.CompletedProcess:
    log.info("$ %s", cmd if len(cmd) < 220 else cmd[:220] + " ...")
    res = subprocess.run(cmd, shell=True, check=False, capture_output=True, text=True)
    if res.returncode != 0 and check:
        log.error("stderr tail:\n%s", res.stderr[-2000:])
        raise subprocess.CalledProcessError(res.returncode, cmd,
                                            output=res.stdout, stderr=res.stderr)
    return res


def _probe_duration(path: Path) -> float:
    out = run(f"ffprobe -v error -show_entries format=duration "
              f"-of default=nw=1:nk=1 {shlex.quote(str(path))}")
    return float(out.stdout.strip())


def _find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _track_color(track: str) -> tuple[int, int, int]:
    return {"A": TRACK_A, "B": TRACK_B}.get(track, NEUTRAL)


def _build_caption_overlay(scene: Scene, out: Path) -> Path | None:
    """Render a 1920x1080 transparent PNG with only the lower-third caption.

    Applied AFTER zoompan via ffmpeg overlay, so the caption stays pinned
    to the output frame regardless of Ken Burns pan/zoom.
    Returns None when the scene has no caption (chapter cards).
    """
    if not scene.caption:
        return None

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    bar_h = 124
    draw.rectangle((0, H - bar_h, W, H), fill=(0, 0, 0, 205))

    accent_w = 6
    accent = _track_color(scene.track)
    draw.rectangle((0, H - bar_h, accent_w, H), fill=(*accent, 255))

    tag_font = _find_font(20)
    cap_font = _find_font(32)

    pad_l = 48
    pad_b = 24

    if scene.track in ("A", "B"):
        tag_text = f"TRACK {scene.track}"
        draw.text((pad_l, H - bar_h + pad_b - 2), tag_text,
                  fill=(*accent, 255), font=tag_font)
        cap_y = H - bar_h + pad_b + 26
    else:
        cap_y = H - bar_h + (bar_h - 32) // 2 - 2

    draw.text((pad_l, cap_y), scene.caption,
              fill=(255, 255, 255, 255), font=cap_font)

    overlay.save(out, "PNG", optimize=True)
    return out


def _tts_scene(scene: Scene, idx: int) -> tuple[Path, float]:
    """Generate the scene's audio clip; return (m4a_path, duration_s).

    For silent chapter cards (narration == '') we synthesize a silent
    clip of `scene.silent_pad` seconds.
    """
    m4a = AUDIO_CLIPS_DIR / f"scene_{idx:02d}.m4a"
    if not scene.narration.strip():
        dur = scene.silent_pad or 2.0
        run(f"ffmpeg -y -f lavfi -i anullsrc=r=22050:cl=mono -t {dur:.3f} "
            f"-c:a aac -b:a 64k {shlex.quote(str(m4a))}")
        return m4a, dur

    aiff = AUDIO_CLIPS_DIR / f"scene_{idx:02d}.aiff"
    text_path = AUDIO_CLIPS_DIR / f"scene_{idx:02d}.txt"
    text_path.write_text(scene.narration)
    run(f"say -v {TTS_VOICE} -r {TTS_RATE} -o {shlex.quote(str(aiff))} "
        f"-f {shlex.quote(str(text_path))}")
    run(f"afconvert -f m4af -d aac -b 64000 "
        f"{shlex.quote(str(aiff))} {shlex.quote(str(m4a))}")
    aiff.unlink()
    return m4a, _probe_duration(m4a)


def _kenburns_filter(scene: Scene, duration: float) -> str:
    d = int(round(duration * FPS))
    fx, fy = scene.focus
    end_zoom = 1.12
    if scene.zoom_dir == "out":
        z_expr = f"'if(lte(zoom,1.0),{end_zoom},max(1.0,zoom-0.0006))'"
    else:
        z_expr = f"'min(zoom+0.0006,{end_zoom})'"
    x_expr = f"'iw*{fx}-(iw/zoom/2)'"
    y_expr = f"'ih*{fy}-(ih/zoom/2)'"
    return (f"zoompan=z={z_expr}:x={x_expr}:y={y_expr}:d={d}:"
            f"s={W}x{H}:fps={FPS}")


def _build_scene(scene: Scene, duration: float, idx: int) -> Path:
    """Render the Ken-Burns clip, then overlay the pinned caption."""
    out = SCENES_DIR / f"scene_{idx:02d}.mp4"
    frame_path = FRAMES / scene.frame
    assert frame_path.exists(), f"missing frame {frame_path}"

    overlay_path = CAPTIONED_DIR / f"scene_{idx:02d}_caption.png"
    overlay = _build_caption_overlay(scene, overlay_path)

    fade_in = 0.35
    fade_out = 0.35
    fade_out_start = max(0.0, duration - fade_out)
    n_frames = int(round(duration * FPS))

    kb = _kenburns_filter(scene, duration)

    if overlay is not None:
        filter_complex = (
            f"[0:v]{kb}[bg];"
            f"[bg][1:v]overlay=0:0[withcap];"
            f"[withcap]fade=t=in:st=0:d={fade_in},"
            f"fade=t=out:st={fade_out_start:.3f}:d={fade_out}[v]"
        )
        cmd = (
            f"ffmpeg -y -loop 1 -framerate {FPS} "
            f"-i {shlex.quote(str(frame_path))} "
            f"-loop 1 -framerate {FPS} -i {shlex.quote(str(overlay))} "
            f"-filter_complex {shlex.quote(filter_complex)} "
            f"-map [v] -frames:v {n_frames} "
            f"-c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p "
            f"-r {FPS} {shlex.quote(str(out))}"
        )
    else:
        vf = (
            kb
            + f",fade=t=in:st=0:d={fade_in}"
            + f",fade=t=out:st={fade_out_start:.3f}:d={fade_out}"
        )
        cmd = (
            f"ffmpeg -y -loop 1 -framerate {FPS} "
            f"-i {shlex.quote(str(frame_path))} "
            f"-vf {shlex.quote(vf)} "
            f"-frames:v {n_frames} "
            f"-c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p "
            f"-r {FPS} {shlex.quote(str(out))}"
        )

    run(cmd)
    return out


def _concat_scenes(paths: list[Path], out: Path, *, vcopy: bool = False) -> None:
    """Concat via the ffmpeg concat demuxer (lossless where possible)."""
    listing = out.parent / f"_concat_list_{out.stem}.txt"
    listing.write_text("\n".join(f"file {shlex.quote(str(p))}" for p in paths))
    codec = "-c copy" if vcopy else "-c:a aac -b:a 64k"
    cmd = (f"ffmpeg -y -f concat -safe 0 -i {shlex.quote(str(listing))} "
           f"{codec} {shlex.quote(str(out))}")
    run(cmd)
    listing.unlink()


def _mux(silent_video: Path, audio: Path, out: Path) -> None:
    cmd = (f"ffmpeg -y -i {shlex.quote(str(silent_video))} "
           f"-i {shlex.quote(str(audio))} "
           f"-map 0:v:0 -map 1:a:0 "
           f"-c:v copy -c:a aac -b:a 96k -shortest -movflags +faststart "
           f"{shlex.quote(str(out))}")
    run(cmd)


def main() -> None:
    log.info("rendering %d scenes", len(SCENES))

    audio_clips: list[Path] = []
    scene_clips: list[Path] = []

    for idx, scene in enumerate(SCENES):
        audio_path, audio_dur = _tts_scene(scene, idx)
        video_dur = audio_dur + TAIL_PAD if not scene.silent_pad else audio_dur
        log.info("scene %02d [%s] audio=%.2fs  video=%.2fs  frame=%s",
                 idx, scene.track, audio_dur, video_dur, scene.frame)

        if not scene.silent_pad:
            padded_audio = AUDIO_CLIPS_DIR / f"scene_{idx:02d}_padded.m4a"
            run(f"ffmpeg -y -i {shlex.quote(str(audio_path))} "
                f"-af apad=pad_dur={TAIL_PAD} -c:a aac -b:a 64k "
                f"{shlex.quote(str(padded_audio))}")
            audio_clips.append(padded_audio)
        else:
            audio_clips.append(audio_path)

        scene_clips.append(_build_scene(scene, video_dur, idx))

    log.info("concatenating silent video ...")
    silent = OUT_DIR / "silent.mp4"
    _concat_scenes(scene_clips, silent, vcopy=True)

    log.info("concatenating narration audio ...")
    voiceover = AUDIO_DIR / "voiceover.m4a"
    _concat_scenes(audio_clips, voiceover)

    log.info("muxing final mp4 ...")
    _mux(silent, voiceover, FINAL)

    probe = run(
        f"ffprobe -v error -show_entries "
        f"format=duration:stream=width,height,codec_name "
        f"-of default=nw=1 {shlex.quote(str(FINAL))}"
    )
    log.info("FINAL:\n%s", probe.stdout)
    log.info("wrote %s  (%.1f MB)", FINAL, FINAL.stat().st_size / 1024 / 1024)


if __name__ == "__main__":
    main()
