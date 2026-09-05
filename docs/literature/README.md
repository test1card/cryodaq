# The literature corpus

Reference literature for the assistant's RAG store: cryocoolers, vacuum
technology, cryopumping, outgassing and MLI, and cryogenic measurement.
It exists so that a question like *"is my second stage losing capacity to
contamination or to a worn seal?"* is answered from Radebaugh and the ICC
proceedings rather than from a language model's recollection of them.

## The PDFs are not in this repository

`data/knowledge/literature/**/*.pdf` is git-ignored. Two reasons, and the
second is the binding one:

1. It is roughly 250 MB. Git is the wrong place for it.
2. **Much of it may not be redistributed.** The Lake Shore appendices and
   Model 218 manual, the Keithley/Tektronix handbook, the Leybold and
   Pfeiffer handbooks, the SHI capacity map and cryopump catalogue, and the
   Brooks/CTI and Sumitomo cryopump manuals are vendor copyright. They are
   published free to download, and holding and indexing them for this lab's
   own use is ordinary and legal. Pushing them to a git remote is
   redistribution, which is not.

What *is* source-controlled is the provenance: one TSV per topic in this
directory, `filename<TAB>url`. Rebuild the corpus with:

    tools/fetch_literature.sh              # all topics
    tools/fetch_literature.sh vacuum       # just one

Reruns skip what is already present, so an interrupted fetch resumes.

## Size, measured

97 of the 99 manifest entries fetch successfully — 322 MB on disk, yielding
**16,118 chunks** at the indexer's 1000-character window, and about 95 seconds
of CPU to parse the whole corpus:

| topic | PDFs | chunks |
|---|---:|---:|
| cryocoolers | 27 | 1,480 |
| cryopumps | 14 | 1,096 |
| measurement | 20 | 6,931 |
| outgassing | 12 | 928 |
| vacuum | 24 | 5,683 |
| **total** | **97** | **16,118** |

For scale: the pre-literature corpus was 3,501 chunks, so this is roughly a
5.6x index. Budget the rebuild accordingly — every chunk is one embedding call
to `qwen3-embedding:8b`.

## Licence, by tier

- **Public domain (US Government):** everything from NIST/NBS
  (`trc.nist.gov`, `nvlpubs.nist.gov`, `tsapps.nist.gov`), NASA NTRS, and
  DOE OSTI. Reusable without restriction.
- **CC-BY:** the CERN Yellow Report editions of the CAS lectures
  (`arxiv.org/pdf/2006.*`, `1501.07162`, `1501.07154`), the 2024 CERN
  vacuum-systems chapter, the Euclid water-ice paper, the loss-of-vacuum
  review, and ECSS-Q-ST-70-02C from ESA.
- **arXiv non-exclusive licence:** free to download and to index privately;
  *not* cleared for redistribution. Cite the published CYR version if the
  work is ever republished.
- **Free ICC proceedings:** `cryocooler.org` volumes 14+ only. Volumes 8–13
  are paywalled (Plenum/Kluwer/Springer) and none are included here. Note
  that `cryocooler.org` answers 307 to a signed CDN URL whose signature
  expires — always keep the `cryocooler.org/resources/Documents/Cnn/nnn.pdf`
  form as canonical, never the CDN link.
- **Vendor copyright, free to download, internal use only:** the documents
  listed in reason 2 above.

## Known gaps, recorded so nobody re-searches them

- **Bulk SiC thermal conductivity at cryogenic temperature has no free
  authoritative dataset.** NBS Monograph 131 mentions SiC only in its
  bibliography; the NIST database does not carry it. The right move is to
  treat SiC as the thing being measured and validate the apparatus against
  OFHC copper or 304 stainless, which do have free reference data.
- **CERN Document Server (`cds.cern.ch`) is behind a bot challenge** and
  returns HTML to any scripted client. Every CDS-hosted document here is
  fetched from its arXiv, OSTI or `cas.web.cern.ch` mirror instead.
- **Two files yield nothing at all**, measured rather than assumed:
  `cryocoolers/radebaugh-1986-comparison-of-three-pulse-tube-types.pdf` has no
  text layer, and `outgassing/ecss-q-st-70-02c-thermal-vacuum-outgassing-test.pdf`
  is encrypted (the loader skips encrypted PDFs by design — decrypting is the
  operator's call, not the loader's). Both are kept as citation targets.
- **Two more are text-sparse and effectively inert**: NBS Monograph 131 yields
  about 400 words across its first 25 pages and NIST Monograph 175 about 221 —
  roughly page headers only. They are the two largest files in the corpus and
  they are exactly the two whose value is in numerical tables, which is what a
  partial OCR loses first. Treat any answer sourced from them with suspicion
  until they are re-OCRed. NASA TP-1177 and the ORNL molecular-sieve report,
  by contrast, do carry good text (7.4k and 4.5k words per 25 pages).
- **Two documents could not be fetched at all**: both USPAS items
  (`uspas.fnal.gov`) answer HTTP 403 to any scripted client. They download
  normally from a browser; drop them into `data/knowledge/literature/outgassing/`
  under the manifest filename if you want them.
- Deliberately excluded on licence grounds: manufacturer service bulletins
  re-hosted on third-party servers. Get the equivalent for this lab's own
  machine from the vendor against its serial number; that copy is
  unambiguously licensed to us.

## Definitive works that are not free

Named here as citation targets; source them through a library. Ekin,
*Experimental Techniques for Low-Temperature Measurements*; Pobell, *Matter
and Methods at Low Temperatures*; Jousten (ed.), *Handbook of Vacuum
Technology*; O'Hanlon, *A User's Guide to Vacuum Technology*; Haefer,
*Cryopumping: Theory and Practice*; Barron, *Cryogenic Systems*; de Waele,
"Basic Operation of Cryocoolers and Related Thermal Machines" (*J. Low Temp.
Phys.* **164**, 179, 2011).
