# Data

Nothing in this folder is committed.

`python pipeline/load_finn_data.py download` downloads the three FINN files into `data/source/`:

| File | Content |
|---|---|
| `data.npz` | Slates and clicks for about 2.3 million users (about 1.3 GB) |
| `itemattr.npz` | The item group of each item |
| `ind2val.json` | Names of the item groups and interaction types |

The files are published by FINN.no at https://github.com/finn-no/recsys_slates_dataset
and hosted on Google Drive. If the download fails, get them manually from the links in
that repository and place them in `data/source/`.

`python pipeline/load_finn_data.py extract` writes the sampled, flattened tables to
`data/processed/`.
