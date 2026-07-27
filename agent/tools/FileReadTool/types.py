# Read 工具的数据类(多模态预留,对标 CC FileReadTool 的 TextFile/ImageFile/...)。
# 现阶段 Read 工具只处理文本,这些类保留供后续多模态扩展(PDF/图片/notebook)。
from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class ReadFileInput:
    filePath: str
    offset: int
    limit: int
    pages: int


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
