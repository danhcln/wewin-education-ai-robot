"""Bounded text extraction for knowledge uploads; original files are not retained."""
from io import BytesIO
import zipfile
from xml.etree import ElementTree
from fastapi import HTTPException

def extract(data: bytes,filename: str):
    lower=filename.lower()
    try:
        if lower.endswith(('.txt','.md')):
            content=data.decode('utf-8-sig')
        elif lower.endswith('.docx'):
            with zipfile.ZipFile(BytesIO(data)) as archive:
                files=archive.infolist()
                if len(files)>2000 or sum(f.file_size for f in files)>32*1024*1024:
                    raise ValueError('expanded_limit')
                info=archive.getinfo('word/document.xml')
                if info.file_size>4*1024*1024:
                    raise ValueError('document_limit')
                xml=archive.read(info)
                if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
                    raise ValueError('xml_declaration')
                document=ElementTree.fromstring(xml)
                ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                content='\n'.join(''.join(t.text or '' for t in paragraph.iter(ns+'t')) for paragraph in document.iter(ns+'p'))
        else:
            raise HTTPException(415,'Hỗ trợ DOCX / TXT / MD. PDF cần bộ trích xuất bổ sung.')
    except (UnicodeDecodeError,ValueError,KeyError,zipfile.BadZipFile,ElementTree.ParseError,RuntimeError):
        raise HTTPException(422,'Tài liệu không hợp lệ, mã hóa không phải UTF-8 hoặc vượt giới hạn giải nén') from None
    if not content.strip() or len(content)>200000 or '\x00' in content:
        raise HTTPException(422,'Nội dung rỗng, không phải văn bản hoặc quá 200.000 ký tự')
    return content
