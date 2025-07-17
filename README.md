# EDS800 Parameter Editor

**Version 1.8.5**

A Python-based graphical user interface (GUI) application for reading, editing, and writing parameters to the EDS800 inverter via Modbus RTU protocol. The application uses a Tkinter-based interface with a table for parameter management and supports Binary-Coded Decimal (BCD) encoding for specific parameters. Parameters in groups `FF` (passwords and manufacturer settings) and `C` (monitoring) are excluded from reading, writing, and saving operations.

## Features
- **Read Parameters**: Read parameters from a selected group or all groups (`F0`–`Fd`) from the inverter.
- **Edit Parameters**: Modify parameter values in a table interface with validation for ranges and formats.
- **Write Parameters**: Save changes for a selected group to the inverter.
- **Write All Parameters**: Write all loaded parameters to the inverter (excluding `FF` and `C` groups).
- **Save to File**: Save all parameters (excluding `FF` and `C`) to a JSON file.
- **Load from File**: Load parameters from a JSON file into the table for editing.
- **BCD Support**: Handles BCD encoding for parameters `F0.03`, `F2.11`, `F2.12`, `F6.01`, `F9.11`, `F2.13`, `F4.00`, `F4.01`, `F4.03`, `F4.05`, `F4.07`, `F4.09`, `F4.11`, `F4.13` (e.g., `1111` → `4369`, `010` → `16`).
- **COM Port Selection**: Automatically detects and lists available COM ports for Modbus communication.

## Requirements
- **Python**: Version 3.6 or higher.
- **Libraries**:
  - `pymodbus`: For Modbus RTU communication.
  - `tksheet`: For the table-based GUI.
  - `pyserial`: For serial port communication.
- **Hardware**: EDS800 inverter connected via a Modbus RTU-compatible serial interface (e.g., USB-to-RS485 adapter).

## Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/eds800-parameter-editor.git
   cd eds800-parameter-editor
   ```
2. Install required Python libraries:
   ```bash
   pip install pymodbus tksheet pyserial
   ```
3. Ensure the `parameters.py` file is in the same directory as `inverter_parameter_editor.py`. This file contains parameter definitions (codes, addresses, ranges, etc.).

## Usage
1. **Run the Application**:
   ```bash
   python inverter_parameter_editor.py
   ```
2. **Interface Overview**:
   - **COM Port Selection**: Choose a COM port from the dropdown menu or click "Refresh Ports" to update the list.
   - **Group Selection**: Select a parameter group (`F0`–`Fd`) from the dropdown menu.
   - **Table**: View and edit parameter values in the table. Only the "Value" column is editable.
   - **Buttons**:
     - **Read Group**: Read parameters for the selected group from the inverter.
     - **Save Group**: Write edited parameters for the selected group to the inverter.
     - **Read All Parameters**: Read all parameters (excluding `FF` and `C`) from the inverter.
     - **Save All Settings to File**: Save all parameters to a JSON file.
     - **Load from File**: Load parameters from a JSON file into the table.
     - **Write All Parameters**: Write all loaded parameters to the inverter (last button).

3. **BCD Parameters**:
   - The following parameters are handled in BCD format:
     - `F0.03` (Run direction setting): Range `000~111` (e.g., `010` → raw `16`).
     - `F2.11`, `F2.12` (LED display control): Range `0000~1111` (e.g., `1111` → raw `4369`).
     - `F6.01` (Traverse run mode): Range `0000~1111`.
     - `F9.11` (Protection action selection): Range `00~11` (e.g., `11` → raw `17`).
     - `F2.13` (Parameter operation control): Range `000~432` (e.g., `432` → raw `1074`).
     - `F4.00` (Simple PLC running setting): Range `0000~3212` (e.g., `3212` → raw `12818`).
     - `F4.01`, `F4.03`, `F4.05`, `F4.07`, `F4.09`, `F4.11`, `F4.13` (Section settings): Range `000~621` (e.g., `621` → raw `1569`).

4. **Saving and Loading**:
   - Save parameters to a JSON file (e.g., `settings.json`) using "Save All Settings to File".
   - Load parameters from a JSON file (e.g., `2.json`) using "Load from File" for editing or writing to the inverter.

## Configuration
- **parameters.py**: Ensure this file defines all parameters (`F0`–`Fd`) with correct attributes:
  - `code`: Parameter code (e.g., `F0.03`).
  - `description`: Parameter description.
  - `unit`: Unit of measurement (e.g., `Hz`, `s`, or empty for BCD parameters).
  - `address`: Modbus register address (e.g., `0x0003` for `F0.03`).
  - `group`: Parameter group (e.g., `F0`).
  - `default`: Default value.
  - `scale`: Scaling factor (e.g., `100` for Hz, `1` for BCD).
  - `range`: Valid range (e.g., `000~111` for `F0.03`).
- Example entry in `parameters.py`:
  ```python
  PARAMETERS = [
      {
          "code": "F0.03", "description": "Run direction setting", "unit": "",
          "address": 0x0003, "group": "F0", "default": "100", "scale": 1, "range": "000~111"
      },
      {
          "code": "F2.11", "description": "LED display control 1", "unit": "",
          "address": 0x020B, "group": "F2", "default": "1111", "scale": 1, "range": "0000~1111"
      },
      # Add other parameters as needed
  ]
  ```

## Testing
1. **Setup**:
   - Connect the EDS800 inverter via a Modbus RTU-compatible serial interface.
   - Ensure `parameters.py` is correctly configured.

2. **Verify Interface**:
   - Run the program and check the button panel:
     - Buttons: "Read All Parameters", "Save All Settings to File", "Load from File", "Write All Parameters" (in this order, with "Write All Parameters" last).
   - Confirm that group `FF` is absent from the group dropdown.

3. **Test Parameter Operations**:
   - **Read Group**: Select a group (e.g., `F0`) and click "Read Group". Verify that parameters like `F0.03` display correctly (e.g., `010` for raw `16`).
   - **Save Group**: Edit a value (e.g., `F0.03` to `011`) and click "Save Group". Check the inverter display.
   - **Read All Parameters**: Click "Read All Parameters" and verify that only `F0`–`Fd` parameters are loaded.
   - **Save All Settings to File**: Save parameters to a JSON file and confirm it matches the format of `2.json`, containing only `F0`–`Fd`.
   - **Load from File**: Load a JSON file (e.g., `2.json`) and verify that parameters display correctly in the table.
   - **Write All Parameters**: Load a JSON file, edit values, and click "Write All Parameters". Verify that changes are applied to the inverter.

4. **Test BCD Parameters**:
   - Set non-zero values on the inverter and read:
     - `F0.03`: Set `011`, expect raw `17`, displayed `011`.
     - `F2.11`, `F2.12`: Set `1111`, expect raw `4369`, displayed `1111`.
     - `F6.01`: Set `1111`, expect raw `4369`.
     - `F9.11`: Set `11`, expect raw `17`.
     - `F2.13`: Set `432`, expect raw `1074`.
   - Check logs (e.g., in the console or a log file):
     ```
     Read F2.12: raw=4369, formatted=1111
     Written F0.03: 16 (from 010)
     Settings saved to file: settings.json
     ```

5. **Troubleshooting**:
   - If parameters `FF` or `C` appear, check `parameters.py` or share logs.
   - If BCD decoding fails (e.g., `F6.01` displays incorrectly), verify raw values and report.

## Logging
- The program logs all operations to the console using Python's `logging` module.
- Example logs:
  ```
  INFO: Read F0.03: raw=16, formatted=010
  INFO: Settings saved to file: settings.json
  ERROR: Failed to read F2.12
  ```
- To save logs to a file, modify the logging configuration in the code:
  ```python
  logging.basicConfig(level=logging.INFO, filename='eds800.log', filemode='w')
  ```

## Known Limitations
- Parameters `FF` and `C` are excluded from all operations to avoid accessing sensitive or read-only data.
- Some BCD parameters (`F6.01`, `F9.11`, `F2.13`, `F4.00`, etc.) are assumed to use BCD based on their range but require non-zero value testing for confirmation.
- The program assumes a Modbus RTU connection with baudrate 9600, no parity, 1 stop bit, and 8 data bits.

## Contributing
- Fork the repository and submit pull requests for improvements.
- Report issues or suggest features via GitHub Issues.
- Ensure any changes to `parameters.py` align with the EDS800 manual (section 5.2).

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Contact
For questions or support, open an issue on GitHub or contact the maintainer at [your.email@example.com].
