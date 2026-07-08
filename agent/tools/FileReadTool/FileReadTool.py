from dataclasses import dataclass, field
@dataclass
class ReadFileInput:
    filePath:str
    offset: int
    limit: int
    pages: int

from typing import Any, Literal

ReadFileOutput = Literal["TextFile", "ImageFile", "NotebookFile", "PDFFile"]
@dataclass
class TextFile:
    filePath: str
    content: str
    numLines: int
    startLine: int
    totalLines: int
@dataclass
class ImageFile: 
    filePath: str
    base64: str
    mimeType: Literal['image/jpeg', 'image/png']
    originalSize: int
    width: int | None = None
    height: int | None = None

@dataclass
class NotebookFile:
    filePath: str
    cells: list[dict[str, Any]]

@dataclass
class PDFFile:
    filePath: str
    base64: str
    originalSize: int
    pageCount: int