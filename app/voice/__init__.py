"""Voice food-log module — TEXT-ONLY backend.

IMPORTANT — backend NEVER receives audio.

Flow:
    1. User speaks into mobile app (iOS / Android).
    2. Device STT transcribes LOCALLY:
       - iOS:     SFSpeechRecognizer
       - Android: SpeechRecognizer
    3. App POSTs transcript (string) to backend:
       POST /logs/food/text { "text": "comí 100g pollo", "meal_time": "lunch" }
    4. Backend parses text → food_logs row.

Decision: 2026-06-03 (CLAUDE.md session log).
- Whisper deleted (`app/voice/infrastructure/whisper_client.py` removed).
- Cost cap + privacy: audio never leaves user device.
- Backend stack: FastAPI text endpoint + deterministic parser, no model calls.

Module name `voice` retained for backward-compatibility of import paths.
The endpoints process TEXT exclusively.
"""
