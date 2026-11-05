"""An Excel workbook: rows under a bold, filterable header, and a sheet of notes."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

MAX_WIDTH = 60


def workbook(title, header, rows, notes_title, notes):
    """The .xlsx file's bytes, written row by row (openpyxl's write-only mode:
    a large download does not hold every cell in memory). Every text cell
    stays text: openpyxl would write one starting with "=" as a formula, and
    the text comes from VM names and guests."""
    book = Workbook(write_only=True)
    sheet = book.create_sheet(title)
    # control characters (a name typed at a failed login) cannot be in the file: written as \x01
    rows = [[ILLEGAL_CHARACTERS_RE.sub(lambda m: f"\\x{ord(m.group()):02x}", value) if isinstance(value, str) else value
             for value in values] for values in [header, *rows]]
    for index, column in enumerate(zip(*rows), start=1):
        width = max(len(str(value or "")) for value in column) + 2
        sheet.column_dimensions[get_column_letter(index)].width = min(width, MAX_WIDTH)
    sheet.freeze_panes = "A2"
    for number, values in enumerate(rows):
        cells = []
        for value in values:
            cell = WriteOnlyCell(sheet, value=value)
            if isinstance(value, str):
                cell.data_type = "s"
            if number == 0:
                cell.font = Font(bold=True)
            cells.append(cell)
        sheet.append(cells)
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(header))}{len(rows)}"
    notes_sheet = book.create_sheet(notes_title)
    notes_sheet.column_dimensions["A"].width = MAX_WIDTH * 2
    for line in notes:
        notes_sheet.append([line])
    out = BytesIO()
    book.save(out)
    return out.getvalue()
