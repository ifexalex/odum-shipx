# PDF fonts (FD-41)

Embedded in every generated PDF by `services/excel/pdf_theme.py`, so documents print the naira sign and Chinese text
the built-in Helvetica cannot. Both families are under the SIL Open Font License 1.1 (`OFL.txt`).

| File | Source | Subset |
| --- | --- | --- |
| `NotoSans-Regular.ttf`, `NotoSans-Bold.ttf` | Noto Sans (notofonts.github.io, hinted TTF) | Latin, Latin-1, Latin Extended-A, punctuation, currency symbols (₦), letterlike symbols, arrows, ✓ |
| `NotoSansSC-Regular.ttf` | Noto Sans SC variable font (google/fonts), instanced at weight 400 | GB2312 (6,763 common simplified characters), CJK punctuation, full-width forms |

Rebuilt with fontTools 4.55.3 (not a project dependency; run with `uvx`):

```sh
uvx --from fonttools==4.55.3 fonttools varLib.instancer "NotoSansSC[wght].ttf" wght=400 -o NotoSansSC-full.ttf
uvx --from fonttools==4.55.3 pyftsubset NotoSansSC-full.ttf --text-file=gb2312.txt --output-file=NotoSansSC-Regular.ttf --layout-features='*' --no-hinting
uvx --from fonttools==4.55.3 pyftsubset NotoSans-Regular.ttf --unicodes="U+0020-007E,U+00A0-017F,U+2000-206F,U+20A0-20CF,U+2100-214F,U+2190-21FF,U+2212,U+2713,U+2714" --output-file=NotoSans-Regular.ttf --layout-features='*'
```

`gb2312.txt` is every character that decodes from GB2312 byte pairs 0xA1A1–0xF7FE, plus U+3000–U+303F, U+FF00–U+FFEF and
printable ASCII. A character outside both fonts is reported by `pdf_theme.missing_glyphs`, which the template tests check.
