"""Test-only labelled mocks. Not used by the production runtime path."""

from __future__ import annotations

from pathlib import Path

from app.provider import ProviderError, ProviderNotConfigured, validate_generation


def sample_transcript(label: str = "A") -> dict:
    return {
        "language": "en",
        "segments": [
            {
                "id": "seg_001",
                "startSec": 0.0,
                "endSec": 2.0,
                "text": f"Today we study Bernoulli's equation, take {label}.",
            },
            {
                "id": "seg_002",
                "startSec": 2.0,
                "endSec": 4.0,
                "text": "Pressure plus one half rho v squared plus rho g h is constant.",
            },
        ],
    }


def sample_generation(transcript: dict, heading_prefix: str = "Notes") -> dict:
    first = transcript["segments"][0]["id"]
    second = transcript["segments"][1]["id"] if len(transcript["segments"]) > 1 else first
    payload = {
        "notes": {
            "sections": [
                {
                    "id": "note_1",
                    "heading": f"{heading_prefix}: Bernoulli",
                    "kind": "definition",
                    "body": "For steady incompressible flow, P + 1/2 rho v^2 + rho g h is constant.",
                    "sourceSegmentIds": [first, second],
                }
            ],
            "unsupportedClaims": [],
        },
        "questions": [
            {
                "id": "q_1",
                "prompt": "Which terms appear in Bernoulli's equation as stated?",
                "choices": [
                    {"id": "a", "text": "Pressure, kinetic, and height terms"},
                    {"id": "b", "text": "Only temperature"},
                ],
                "answerId": "a",
                "explanation": "The lecturer listed pressure, 1/2 rho v^2, and rho g h.",
                "sourceSegmentIds": [second],
            }
        ],
    }
    notes, questions = validate_generation(payload, transcript)
    return {"notes": notes, "questions": questions}


class ScriptedProvider:
    """Labelled test double. Records calls so tests can prove rank-then-one-transcribe."""

    def __init__(self, transcribe_plan=None, generate_plan=None):
        self.transcribe_plan = list(transcribe_plan or [])
        self.generate_plan = list(generate_plan or [])
        self.transcribe_calls: list[str] = []
        self.generate_calls: int = 0

    def transcribe(self, audio_path: Path, mime_type: str) -> dict:
        self.transcribe_calls.append(audio_path.name)
        if not self.transcribe_plan:
            return sample_transcript("default")
        item = self.transcribe_plan.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def generate(self, transcript: dict) -> dict:
        self.generate_calls += 1
        if not self.generate_plan:
            return sample_generation(transcript)
        item = self.generate_plan.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(transcript)
        return item


class MissingProvider:
    def transcribe(self, audio_path: Path, mime_type: str) -> dict:
        raise ProviderNotConfigured()

    def generate(self, transcript: dict) -> dict:
        raise ProviderNotConfigured()
