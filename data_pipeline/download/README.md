# Part 1: raw data acquisition

All raw files live in `data/raw/<dataset>/` (git-ignored). Every automated download is recorded in
`data/raw/DOWNLOADS.json` (URL, bytes, sha256, access time, licence).

## Automated
```bash
python -m data_pipeline.download.download_public          # PPD, HPI, NEED, GHG, Met Office, PVGIS, LCL
python -m data_pipeline.download.ons_lad_region            # ONS local authority -> region lookup
```
The sources and licences are listed in `sources.yaml`.

## Manual: EPC (needs a GOV.UK One Login)
1. Open https://get-energy-performance-data.communities.gov.uk/. Do **not** use the
   `epb-integration` link in the problem statement PDF: that is a test site with fake data.
2. Click **Start now**, sign in or create a GOV.UK One Login, and choose **Download files → Domestic EPCs**.
3. Download certificates **and** recommendations for the target local authorities in
   `config/data_pipeline.yaml`, or the national file if per-LA isn't offered.
4. Put the zip(s) or CSV(s) in `data/raw/epc/` without unzipping or renaming. `ingest_epc.py` finds them.

Notes:
- Since March 2026 the certificate id is `CERTIFICATE_NUMBER`. Older files use `LMK_KEY`. Both are handled.
- EPC data is OGL v3, but addresses are © Royal Mail/OS. Addresses are used only to join to Land Registry
  and are dropped before anything leaves `data/interim/`.
