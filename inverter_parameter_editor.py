"""Entry point for the ENC inverter parameter editor.

The application itself lives in the :mod:`enc_editor` package:

    enc_editor/catalog.py     inverter profiles loaded from ``profiles/``
    enc_editor/codecs.py      register bits <-> displayed text
    enc_editor/transport.py   Modbus RTU link
    enc_editor/detection.py   automatic revision detection
    enc_editor/session.py     editing state
    enc_editor/ui/app.py      the Tk window
"""

from enc_editor.ui.app import InverterParameterEditor, main

__all__ = ["InverterParameterEditor", "main"]


if __name__ == "__main__":
    main()
