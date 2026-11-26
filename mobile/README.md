# Lectio mobile application

This is the Flutter/Dart implementation of the Lectio student workflow. It contains no sample class, sample lecture or fixture-powered fallback. Class and lecture data are loaded from the shared service using contract v0.1 and the `X-Invite-Token` access model.

The source includes authenticated playback of the original or noise-reduced recording, timestamp-linked transcript seeking, and authenticated board-photo display. It has not been compiled or device-tested in this workspace because the Flutter and Dart SDKs were not available here. Android/iOS platform folders are generated on the build machine; they are not included in this source-only handoff.

## Create and run the platform projects

From this folder, use a machine with Flutter installed:

```bash
flutter create --platforms=android,ios .
flutter pub get
flutter analyze
flutter test
flutter run
```

The SDK constraint is declared in `pubspec.yaml`. Use a Flutter release that includes a compatible Dart SDK.

## Permissions

Android requires microphone permission in `android/app/src/main/AndroidManifest.xml`:

```xml
<uses-permission android:name="android.permission.RECORD_AUDIO" />
```

iOS requires a microphone usage description inside the top-level `<dict>` in `ios/Runner/Info.plist`:

```xml
<key>NSMicrophoneUsageDescription</key>
<string>Lectio records a lecture only after you confirm you have permission to use the audio.</string>
```

Run on a physical phone or emulator that supports audio input. Confirm the permission prompt, record a short clip, upload it to a connected class, open its notes, tap a source timestamp, switch between original and noise-reduced audio when available, open a timestamped board photo, and test an exported ZIP after disconnecting from the network.

## Connect the class service

The Connection details screen accepts the shared service address. Students join with a class invitation and enter the display name their classmates will see. The contract gives `http://localhost:8000` only as a local development example. It is not a hosted API URL. On an Android emulator, `localhost` points to the emulator itself. Use the host-machine bridge address or a deployed HTTPS URL as appropriate.

All authenticated class, lecture, media and export calls send `X-Invite-Token`. The token is not added to API paths or query strings. Contract v0.1 does not define email/password login, so this app does not invent it.

Students do not need to enter a service address. A class administrator or maintainer must configure and verify the shared service before invitations, uploads and processing can work. The last class is restored on the same device using the saved class ID and invitation token. Leaving the class removes these local credentials only.

## Real class workflow

1. Join a class with the invitation supplied by its representative, or create a class if the service permits it.
2. Open an existing lecture or create one inside the class.
3. Confirm permission before recording or uploading audio and board photos.
4. Contribute a recording that meets the three-minute, 20 MB and accepted-format limits.
5. Compare candidate recordings, process one selected source, and verify notes against their transcript segments.
6. Complete practice questions and download the service-generated study pack when it is available.

The app does not create local-only classes or claim that a recording has reached classmates when the service is unavailable. Board photos load from `/v1/media/{assetId}` with `X-Invite-Token`, and tapping one seeks the selected recording to its supplied timestamp.

## Current limitations

- No deployed backend URL or AI provider configuration was supplied.
- Class creation, joining, recording, upload, processing, media playback and offline export all require the shared backend.
- Flutter compilation, Android/iOS permission flows, native audio recording, file sharing and offline behavior still need testing on target devices.
- The offline study pack is intended for extraction and use in a desktop browser. Mobile `file://` behavior is not guaranteed by contract v0.1.

## Product contract

Read `../docs/contract-v0.1.md`, `../docs/design-decisions.md` and `../docs/handoff.md` before changing shared field names or request behavior. Do not change the backend contract without agreement.
