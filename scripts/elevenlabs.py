#!/usr/bin/env python3
"""
ElevenLabs CLI — Text-to-Speech & Speech-to-Text
Agent-friendly command-line tool. Outputs clean JSON or raw bytes.

Usage:
  python elevenlabs_cli.py tts "Hello world" [options]
  python elevenlabs_cli.py stt audio.mp3 [options]
  python elevenlabs_cli.py voices [options]

Set your API key via env var:  ELEVENLABS_API_KEY=your_key_here
Or pass it with --api-key flag.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path


# ─────────────────────────────────────────────
# HTTP helper (stdlib only — no extra deps)
# ─────────────────────────────────────────────
import urllib.request
import urllib.error


def _api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "sk_f4c64938a57560c5473d634ac7f4a475a50849082429c26e")
    return key


def _headers(api_key: str, extra: dict | None = None) -> dict:
    h = {"xi-api-key": api_key, "Accept": "application/json"}
    if extra:
        h.update(extra)
    return h


def _get(url: str, api_key: str) -> dict:
    req = urllib.request.Request(url, headers=_headers(api_key))
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def _post_json(url: str, api_key: str, payload: dict, accept: str = "application/json"):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers=_headers(api_key, {"Content-Type": "application/json", "Accept": accept}),
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        if accept == "application/json":
            return json.loads(r.read())
        return r.read()  # raw bytes for audio


def _post_multipart(url: str, api_key: str, file_path: str) -> dict:
    """Multipart form upload for STT."""
    import mimetypes, email.generator, io, uuid

    boundary = uuid.uuid4().hex
    mime_type = mimetypes.guess_type(file_path)[0] or "audio/mpeg"
    fname = Path(file_path).name

    with open(file_path, "rb") as f:
        file_data = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "xi-api-key": api_key,
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


# ─────────────────────────────────────────────
# Output helpers
# ─────────────────────────────────────────────

def _out(data: dict | str, json_mode: bool):
    """Print result — JSON object or plain text."""
    if json_mode:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif isinstance(data, dict):
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(data)


def _err(msg: str, code: int = 1):
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(code)


# ─────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────

def cmd_tts(args, api_key: str):
    """Convert text → speech, save to file (or stdout bytes)."""
    text = args.text
    voice_id = args.voice_id or "JBFqnCBsd6RMkjVDRZzb"  # default: George
    model = args.model or "eleven_multilingual_v2"
    output_path = args.output  # None = stdout raw bytes

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    payload = {
        "text": text,
        "model_id": model,
        "voice_settings": {
            "stability": args.stability,
            "similarity_boost": args.similarity_boost,
            "style": args.style,
            "use_speaker_boost": not args.no_speaker_boost,
        },
    }

    try:
        audio_bytes = _post_json(url, api_key, payload, accept="audio/mpeg")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        _err(f"HTTP {e.code}: {body}")

    if output_path:
        Path(output_path).write_bytes(audio_bytes)
        result = {
            "status": "ok",
            "output_file": str(Path(output_path).resolve()),
            "bytes": len(audio_bytes),
            "voice_id": voice_id,
            "model": model,
            "text_length": len(text),
        }
        _out(result, args.json)
    else:
        # Raw bytes to stdout — useful for piping
        sys.stdout.buffer.write(audio_bytes)


def cmd_stt(args, api_key: str):
    """Transcribe audio file → text."""
    file_path = args.file
    model = args.model or "scribe_v1"

    if not Path(file_path).exists():
        _err(f"File not found: {file_path}")

    url = f"https://api.elevenlabs.io/v1/speech-to-text"

    # ElevenLabs STT uses multipart form data
    try:
        # Build multipart manually
        import uuid, mimetypes
        boundary = uuid.uuid4().hex
        mime_type = mimetypes.guess_type(file_path)[0] or "audio/mpeg"
        fname = Path(file_path).name

        with open(file_path, "rb") as f:
            file_data = f.read()

        # Add model field
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="model_id"\r\n\r\n'
            f"{model}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "xi-api-key": api_key,
                "Accept": "application/json",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            data = json.loads(r.read())

    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        _err(f"HTTP {e.code}: {body}")

    transcript = data.get("text", "")

    if args.json:
        _out({
            "status": "ok",
            "transcript": transcript,
            "words": data.get("words", []),
            "language_code": data.get("language_code", ""),
            "model": model,
            "file": file_path,
        }, True)
    else:
        print(transcript)


def cmd_voices(args, api_key: str):
    """List available voices."""
    try:
        data = _get("https://api.elevenlabs.io/v1/voices", api_key)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        _err(f"HTTP {e.code}: {body}")

    voices = data.get("voices", [])

    if args.json:
        _out({"voices": [
            {
                "voice_id": v["voice_id"],
                "name": v["name"],
                "category": v.get("category", ""),
                "labels": v.get("labels", {}),
            }
            for v in voices
        ]}, True)
    else:
        # Pretty table
        print(f"{'Voice ID':<30} {'Name':<25} {'Category'}")
        print("─" * 70)
        for v in voices:
            print(f"{v['voice_id']:<30} {v['name']:<25} {v.get('category','')}")
        print(f"\nTotal: {len(voices)} voices")


def cmd_models(args, api_key: str):
    """List available models."""
    try:
        data = _get("https://api.elevenlabs.io/v1/models", api_key)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        _err(f"HTTP {e.code}: {body}")

    if args.json:
        _out({"models": data}, True)
    else:
        print(f"{'Model ID':<35} {'Name':<30} {'TTS':<5} {'STT'}")
        print("─" * 85)
        for m in data:
            tts = "✓" if m.get("can_do_text_to_speech") else ""
            stt = "✓" if m.get("can_do_voice_conversion") else ""
            print(f"{m['model_id']:<35} {m['name']:<30} {tts:<5} {stt}")


# ─────────────────────────────────────────────
# CLI setup
# ─────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="elevenlabs_cli",
        description="ElevenLabs TTS & STT — agent-friendly CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Text to Speech → save file
  python elevenlabs_cli.py tts "Hello, world!" --output hello.mp3

  # TTS with specific voice and model
  python elevenlabs_cli.py tts "Bonjour!" --voice-id <id> --model eleven_turbo_v2_5 --output out.mp3

  # TTS → pipe to player
  python elevenlabs_cli.py tts "Hi" | ffplay -nodisp -autoexit -i pipe:0

  # Speech to Text
  python elevenlabs_cli.py stt recording.mp3

  # STT → JSON (for agents)
  python elevenlabs_cli.py stt recording.mp3 --json

  # List voices
  python elevenlabs_cli.py voices --json

  # Set API key via env
  export ELEVENLABS_API_KEY=your_key_here
        """,
    )

    parser.add_argument("--api-key", default=None, help="ElevenLabs API key (overrides ELEVENLABS_API_KEY env var)")
    parser.add_argument("--json", action="store_true", help="Output as JSON (default for errors, optional for success)")

    sub = parser.add_subparsers(dest="command", required=True)

    # ── tts ──
    tts_p = sub.add_parser("tts", help="Text → Speech")
    tts_p.add_argument("text", help="Text to synthesize")
    tts_p.add_argument("--voice-id", "-v", default=None, help="Voice ID (default: George/JBFqnCBsd6RMkjVDRZzb)")
    tts_p.add_argument("--model", "-m", default=None, help="Model ID (default: eleven_multilingual_v2)")
    tts_p.add_argument("--output", "-o", default=None, help="Output file path (e.g. out.mp3). If omitted, writes raw bytes to stdout.")
    tts_p.add_argument("--stability", type=float, default=0.5, help="Voice stability 0.0–1.0 (default: 0.5)")
    tts_p.add_argument("--similarity-boost", type=float, default=0.75, help="Similarity boost 0.0–1.0 (default: 0.75)")
    tts_p.add_argument("--style", type=float, default=0.0, help="Style exaggeration 0.0–1.0 (default: 0.0)")
    tts_p.add_argument("--no-speaker-boost", action="store_true", help="Disable speaker boost")
    tts_p.add_argument("--json", action="store_true", help="Output result as JSON")

    # ── stt ──
    stt_p = sub.add_parser("stt", help="Speech → Text")
    stt_p.add_argument("file", help="Audio file path (mp3, wav, m4a, ogg, flac…)")
    stt_p.add_argument("--model", "-m", default=None, help="STT model (default: scribe_v1)")
    stt_p.add_argument("--json", action="store_true", help="Output full JSON including word timestamps")

    # ── voices ──
    voices_p = sub.add_parser("voices", help="List available voices")
    voices_p.add_argument("--json", action="store_true", help="Output as JSON")

    # ── models ──
    models_p = sub.add_parser("models", help="List available models")
    models_p.add_argument("--json", action="store_true", help="Output as JSON")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Resolve API key
    api_key = args.api_key or _api_key()
    if not api_key:
        _err(
            "No API key found. Set ELEVENLABS_API_KEY env var or pass --api-key. "
            "Get your key at https://elevenlabs.io/app/settings/api-keys"
        )

    dispatch = {
        "tts": cmd_tts,
        "stt": cmd_stt,
        "voices": cmd_voices,
        "models": cmd_models,
    }

    try:
        dispatch[args.command](args, api_key)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        _err(str(e))


if __name__ == "__main__":
    main()