"""ENC inverter parameter editor.

Layers, from the drive upwards:

``catalog``     inverter profiles loaded from the ``profiles`` directory
``codecs``      register bits <-> displayed text, one class per encoding
``dependencies``  bounds between parameters: write order and refusals
``transport``   Modbus RTU link: batched reads, writes, cancellation
``detection``   automatic revision detection driven by a profile manifest
``session``     what was read and what the user edited
``i18n``        interface translations
``ui``          the Tk window; the only layer that knows about widgets
"""

from __future__ import annotations

VERSION = "3.1.1"

__all__ = ["VERSION"]
