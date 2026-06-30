# Race Engineer

Standalone race engineer subscriber.

This app listens to `race-table-update` plus the high-frequency
`race-engineer-trace-update` IPC topic, runs the shared `lib.race_engineer`
advisor engine, applies priority/cooldown filtering, and speaks or logs the
callouts.

`lib.race_engineer.azure_voice` includes an Azure Speech Text to Speech
provider. The launcher can start this subsystem manually; it defaults to
dry-run mode until the `RaceEngineer` config section is approved and wired
through settings.

## Manual Run

```bash
poetry run python -m apps.race_engineer --debug --min-priority warning
```

Useful options:

- `--focus fuel`
- `--focus tyres`
- `--focus weather`
- `--min-priority advisory`
- `--min-priority critical`
- `--cooldown-seconds 30`
- `--min-voice-interval-seconds 4`
- `--initial-enabled false`
- `--max-items 3`
- `--max-queue-size 3`
- `--voice-provider azure`
- `--azure-region westeurope`
- `--azure-voice en-US-GuyNeural`
- `--azure-key-env-var PNG_AZURE_SPEECH_KEY`
- `--speech-recognition-provider azure`
- `--push-to-talk-audio-source windows_microphone`
- `--agent-prompts-file C:\path\to\race-engineer-prompts.json`
- `--write-agent-prompts-template C:\path\to\race-engineer-prompts.json`
- `--conversation-provider http`
- `--conversation-endpoint http://127.0.0.1:8765/race-engineer/answer`
- `--conversation-provider codex_cli`
- `--conversation-command "codex-wrapper --answer-race-engineer"`
- `--profile-check`
- `--profile-audio-question-test C:\path\to\question.wav`
- `--profile-mic-question-test-seconds 3`
- `--profile-preflight`
- `--profile-preflight-question "как топливо?"`
- `--profile-question-test "как топливо?"`
- `--profile-voice-test "Race engineer online."`
- `--question-test "как топливо?"`
- `--question-snapshot C:\path\to\race-table-update.json`
- `--voice-test "Race engineer online."`

Logs go to `png_race_engineer.log` by default.

By default, the app allows `advisory` and higher-priority callouts so
driving-coach feedback can be heard, then uses cooldowns and the global voice
interval to keep the radio quiet.

Lap-to-lap pace calls compare the player's last lap against the cars directly
ahead and behind. Once enough laps are available, the call also includes a
compact rolling average over the last three comparable laps, so battle advice is
less sensitive to one messy lap.

`--voice-test` logs the selected provider, total voice duration, and synthesized
audio byte count. Azure synthesis retries transient 408/429/5xx failures once
before reporting an error. In managed mode, launcher stats also include the last
voice result and the voice failure count.

When a new telemetry session UID is detected, pending callouts, cooldowns, and
trace references are reset so old-session advice is not spoken in the next run.
Critical callouts also preempt lower-priority pending callouts in the voice
queue, so urgent tyre/fuel/damage messages are spoken first.
Non-critical callouts are also globally rate-limited by
`--min-voice-interval-seconds`, which keeps the engineer from talking too often
during busy laps.

## Launcher Run

The launcher shows a `Race Engineer` subsystem card. It is manual-start for
now, so current users do not get new audio by surprise. The card also has a
settings button that edits `race_engineer_profile.json`, a launcher-side profile
kept outside the main telemetry config.

When the subsystem is running, the card exposes quick live controls:

- mute/unmute automatic callouts without restarting the process.
- run a short radio check through the configured voice provider.
- ask a typed question, using the same answer path as push-to-talk voice
  questions. Typed questions use the profile's answer timeout plus a small
  launcher IPC grace period, so slower Codex/HTTP providers are not reported as
  failed before their configured timeout.

Runtime stats include `assistant-status` and `assistant-status-detail`, covering
states such as muted, waiting for telemetry, listening, speaking, queued voice,
and the last voice/speech/question error. The launcher card polls those stats
while the process is running and shows a compact live badge such as `Online`,
`Listening`, `Speaking`, `Muted`, or `No Telemetry`.

The settings dialog also has `Check`, `Voice Test`, `Question Test`,
`Audio Q Test`, `Mic PTT Test`, and `Preflight` buttons. `Check` runs offline setup diagnostics for the profile: Azure
endpoint/region, key environment variable presence, STT/PTT compatibility,
Codex CLI command shape, prompt file path, and UDP action conflicts. It does
not contact Azure and does not print secret values. `Voice Test` runs a
one-message profile voice smoke test from the current form values through a
temporary profile, so the saved profile is not changed unless `Save` is
pressed. `Question Test` asks one typed question through the current local,
HTTP, or `codex_cli` answer provider and shows the returned answer.
`Audio Q Test` lets you choose a WAV file and runs the full profile path:
Azure STT transcript, answer provider, and voice output. `Mic PTT Test` records
the configured local Windows microphone for a few seconds and runs the same
STT -> answer -> voice pipeline, so the real push-to-talk audio chain can be
checked before driving. `Preflight` combines diagnostics, one voice smoke test,
one profile question smoke test, and a push-to-talk readiness report into a
single ready/not-ready result with next steps such as setting the Azure key,
running `Mic PTT Test`, or restarting the backend after UDP binding changes.
For a missing Azure key, the next step includes the exact PowerShell env-var
assignment with a placeholder instead of printing or storing the secret. It does
not record the microphone by surprise; for that live recording check use `Mic
PTT Test`.

The `Prompts` tab can create an editable JSON template with every advisor
category and the current default prompt contract. Edit only the category fields
you want to override, then keep that file selected in the profile.

The same check is available from the command line:

```powershell
poetry run python -m apps.race_engineer --profile-check
```

Use `--profile-file C:\path\to\race_engineer_profile.json` to check a profile
other than the launcher default.

To smoke-test the exact voice settings saved by the launcher profile, run:

```powershell
poetry run python -m apps.race_engineer --profile-voice-test "Race engineer online."
```

This reads `race_engineer_profile.json`, uses the configured voice provider,
Azure endpoint, voice, output format, and key environment variable name, speaks
one short message, then exits before connecting to telemetry.

You can also smoke-test the question-answer provider without the game:

```powershell
poetry run python -m apps.race_engineer --question-test "как топливо?"
```

Without `--question-snapshot`, this uses a small synthetic race-table snapshot
with a fuel deficit so local, HTTP, or `codex_cli` answer providers can be tested
offline. Pass `--question-snapshot` to test against a captured `race-table-update`
JSON object instead.

To use the saved launcher profile's question provider and prompt file:

```powershell
poetry run python -m apps.race_engineer --profile-question-test "как топливо?"
```

To smoke-test the voice-question path from an audio file:

```powershell
poetry run python -m apps.race_engineer --profile-audio-question-test C:\path\to\question.wav
```

This loads the saved profile, sends the audio to the configured speech
recognizer, asks the transcribed question through the configured answer
provider, speaks the answer through the configured voice provider, and prints
one JSON summary.

To smoke-test the live microphone path used by wheel push-to-talk:

```powershell
poetry run python -m apps.race_engineer --profile-mic-question-test-seconds 3
```

This requires `speech_recognition_provider=azure` and
`push_to_talk_audio_source=windows_microphone` in the launcher profile. It
records the default Windows microphone, wraps the PCM as WAV, sends it to Azure
STT, answers the transcript, speaks the answer, and prints one JSON summary.

To run the same combined pre-drive check used by the launcher `Preflight`
button:

```powershell
poetry run python -m apps.race_engineer --profile-preflight --profile-preflight-question "как топливо?"
```

The command prints one JSON summary with diagnostics, voice status, question
status, push-to-talk readiness, and a `next_steps` checklist, then exits before
connecting to telemetry.

The profile covers:

- online/muted startup state, focus, priority, cooldown, and voice queue limits.
- Azure TTS endpoint, voice, output format, and key environment variable name.
- Azure STT language and push-to-talk audio source.
- local, HTTP/Codex-compatible, or local Codex CLI conversation provider settings.
- category prompt override JSON file.
- race engineer toggle and push-to-talk UDP action codes.

Managed launcher mode uses environment variables for optional voice settings:

```powershell
$env:PNG_RACE_ENGINEER_VOICE_PROVIDER = "azure"
$env:PNG_AZURE_SPEECH_REGION = "westeurope"
$env:PNG_AZURE_SPEECH_ENDPOINT = "https://francecentral.api.cognitive.microsoft.com/"
$env:PNG_AZURE_SPEECH_KEY = "<your Azure Speech key>"
$env:PNG_RACE_ENGINEER_MIN_VOICE_INTERVAL_SECONDS = "4"
poetry run python -m apps.launcher
```

For voice questions, set Azure STT and choose the push-to-talk audio source:

```powershell
$env:PNG_RACE_ENGINEER_SPEECH_RECOGNITION_PROVIDER = "azure"
$env:PNG_AZURE_STT_LANGUAGE = "ru-RU"
$env:PNG_RACE_ENGINEER_PUSH_TO_TALK_AUDIO_SOURCE = "windows_microphone"
poetry run python -m apps.launcher
```

`external` remains the default push-to-talk audio source. In that mode another
client can send `race-engineer-ptt-control` plus `race-engineer-ptt-audio`
messages. `windows_microphone` records the local default Windows microphone
while the push-to-talk control is active.
When the engineer is muted, push-to-talk does not start recording and audio
questions do not call Azure STT; the app speaks a short muted status instead.

UDP action bindings saved in the launcher profile are read by the backend at
startup. Restart the backend after changing the wheel-button bindings.
If a push-to-talk UDP action is bound, `Check` and `Preflight` require speech
recognition to be enabled so a wheel button cannot silently do nothing.

By default, spoken questions are answered by the local compressed-brief agent.
To route question answering to a Codex-compatible local proxy, keep Azure as the
audio layer and set the HTTP conversation provider:

```powershell
$env:PNG_RACE_ENGINEER_CONVERSATION_PROVIDER = "http"
$env:PNG_RACE_ENGINEER_CONVERSATION_ENDPOINT = "http://127.0.0.1:8765/race-engineer/answer"
$env:PNG_RACE_ENGINEER_CONVERSATION_KEY_ENV_VAR = "PNG_CODEX_PROXY_KEY"
```

The HTTP endpoint receives only a compact prompt package: the driver's question,
advisor prompt specs, current facts, advice, review status, battle context, and
a radio answer contract. It does not receive raw race-table rows or packet-level
telemetry. The answer contract asks external providers to answer in the same
language as the question, in at most two short race-radio sentences with no
markdown or bullet list. If the endpoint fails, the race engineer falls back to
the local brief answerer.

For a local Codex CLI flow, select `codex_cli` and configure a command. The app
runs the command without a shell, sends the same compact prompt package as JSON
on stdin, and accepts either `{"answer": "..."}` JSON or plain text on stdout:

```powershell
$env:PNG_RACE_ENGINEER_CONVERSATION_PROVIDER = "codex_cli"
$env:PNG_RACE_ENGINEER_CONVERSATION_COMMAND = "codex-wrapper --answer-race-engineer"
```

The wrapper can call whatever Codex CLI command is installed locally. If the
command exits non-zero, times out, or returns an empty answer, the race engineer
falls back to the local brief answerer.

Custom category prompts can be loaded from a JSON file without storing secrets
or changing the main config yet:

```powershell
poetry run python -m apps.race_engineer --write-agent-prompts-template C:\path\to\race-engineer-prompts.json
```

```json
{
  "prompts": {
    "tyres": {
      "role": "Tyre Life Engineer",
      "system_prompt": "Focus on tyre life, asymmetric wear, and exit traction.",
      "call_policy": "Speak only when tyre evidence changes the next lap plan."
    },
    "fuel": {
      "role": "Fuel Coach",
      "system_prompt": "Convert fuel burn evidence into calm lift-and-coast calls."
    }
  }
}
```

```powershell
$env:PNG_RACE_ENGINEER_AGENT_PROMPTS_FILE = "C:\path\to\race-engineer-prompts.json"
```

Azure keys should be passed through the environment, not stored in config or
command history:

```powershell
$env:PNG_AZURE_SPEECH_KEY = "<your Azure Speech key>"
poetry run python -m apps.race_engineer --voice-provider azure --azure-speech-endpoint https://francecentral.api.cognitive.microsoft.com/ --voice-test
```

If the same Azure values are already saved in the launcher profile, prefer:

```powershell
$env:PNG_AZURE_SPEECH_KEY = "<your Azure Speech key>"
poetry run python -m apps.race_engineer --profile-voice-test
```
