"""Cross-cutting helpers importable from every layer.

Deliberately tiny: settings, logging, context vars. No business concepts and no
I/O clients. A ``shared`` package that grows past a few hundred lines has become
a dumping ground (02_Project_Structure.md §6).
"""
