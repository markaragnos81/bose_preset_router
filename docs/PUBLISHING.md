# Publishing Checklist

## 1. Create the GitHub repository

- Create a public GitHub repository
- Recommended repository name: `bose_preset_router`
- Add a repository description
- Add topics like `home-assistant`, `hacs`, `bose`, `soundtouch`, `music-assistant`

## 2. Replace placeholders

Update these values in `manifest.json`:

- `documentation`
- `issue_tracker`
- `codeowners`

Replace `YOUR_GITHUB_USER` with your real GitHub username.

## 3. Push the code

Push the repository to GitHub and verify that these workflows pass:

- `.github/workflows/hacs.yaml`
- `.github/workflows/hassfest.yaml`

## 4. Add a license

Choose a license before publishing publicly.

Common choices:

- MIT
- Apache-2.0

## 5. Create a GitHub release

For HACS users, create a proper GitHub release after the workflows pass.

Recommended first release:

- `v0.3.0` if you want to keep the current version
- or a newer version if you want to publish the recent improvements as a new release

## 6. Add the repository to HACS

In Home Assistant:

1. Open HACS
2. Open `Custom repositories`
3. Add the GitHub repository URL
4. Select category `Integration`
5. Install `Bose Preset Router`

## 7. Optional next step

If you want the integration to appear in the default HACS store later, make sure:

- the repository remains public
- HACS validation passes
- Hassfest passes
- the integration has active maintenance
- you create releases regularly
