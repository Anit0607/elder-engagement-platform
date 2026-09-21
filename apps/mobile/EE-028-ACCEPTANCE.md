# EE-028 Android shell acceptance

Status: **in progress**, not client-accepted.

Automated checks:

- Home, Circles and Profile navigation renders and switches.
- English, Bengali and Hindi labels and main screen text switch together.
- Type-check, lint and dependency audit pass.
- Android debug package must build successfully on D and in GitHub Actions.
- Self-contained `clientTest` package must bundle its screens for phone review.

Client phone check still required:

1. Install the new React Native debug package on a supported Android phone.
2. Open Home, Circles and Profile; confirm each screen responds and remains readable.
3. Switch to Bengali, visit all three areas, and then repeat in Hindi and English.
4. Enlarge Android display/font size and check that text and controls remain usable.

This is only the navigation shell. Sign-in/profile actions and live circle data are
separate EE-029 and EE-030 acceptance checks. Logo, final colours, icon and
reviewed screen wording remain client inputs; placeholder branding is not a
production acceptance claim.
