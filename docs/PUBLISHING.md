# Publishing Checklist

## Versioning Policy

This project uses Semantic Versioning (`MAJOR.MINOR.PATCH`).

- Increase `PATCH` for fixes, small improvements, documentation-only releases, and non-breaking maintenance
- Increase `MINOR` for new backwards-compatible features
- Increase `MAJOR` for breaking changes in behavior, configuration, or compatibility

The version in `manifest.json`, the release tag, and the changelog entry should always match.

## Release Workflow

Before creating a release:

1. Update `manifest.json` to the next version
2. Move relevant notes from `CHANGELOG.md` under `Unreleased` into a dated version section
3. Commit the changes
4. Push to GitHub
5. Verify that these workflows pass:
   - `.github/workflows/hacs.yaml`
   - `.github/workflows/hassfest.yaml`
6. Create a GitHub release with the same tag as the manifest version, for example `v0.3.1`

## Repository Basics

- Keep the repository public if it should be installable via HACS custom repositories
- Maintain a repository description and useful topics such as `home-assistant`, `hacs`, `bose`, `soundtouch`, `music-assistant`
- Keep `manifest.json` links aligned with the real repository URL

## HACS Installation

In Home Assistant:

1. Open HACS
2. Open `Custom repositories`
3. Add the GitHub repository URL
4. Select category `Integration`
5. Install `Bose Preset Router`

## Optional Next Step

If you want the integration to appear in the default HACS store later, make sure:

- the repository remains public
- HACS validation passes
- Hassfest passes
- the integration has active maintenance
- you create releases regularly
