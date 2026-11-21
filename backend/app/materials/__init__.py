"""Course materials in bulk (the night of 21-22 November): a folder of syllabi, lab books,
textbooks, homework sheets -> courses, weekly plans, tables of contents mapped to weeks and
searchable passages. Run in the development stack, checked there, then carried to the live
one as a bundle (app.materials.bundle).

    python -m app.materials.ingest /materials            # the folder mounted in dev
    python -m app.materials.ingest /materials --dry-run  # only what goes where

Personal materials never enter the repository (syllabus/, materials/, data/ are ignored).
"""
