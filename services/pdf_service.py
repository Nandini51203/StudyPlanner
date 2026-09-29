import config


def extract_text(stream, ext):
    """Extract text from PDF or TXT file with validation."""
    if ext == "txt":
        text = stream.read().decode("utf-8", errors="ignore")
    elif ext == "pdf":
        from pypdf import PdfReader
        try:
            reader = PdfReader(stream)
            # Validate page count
            if len(reader.pages) > config.MAX_PDF_PAGES:
                raise ValueError(f"PDF exceeds {config.MAX_PDF_PAGES} pages (has {len(reader.pages)}).")
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        except ValueError:
            raise
        except Exception:
            raise ValueError("Could not read this PDF (corrupt or encrypted).")
    else:
        raise ValueError("Unsupported file format.")

    text = text.strip()
    if not text:
        raise ValueError("No extractable text found (empty file or scanned PDF).")
    return text


def get_page_count(stream, ext):
    """Get PDF page count without extracting all text. Returns 1 for TXT."""
    if ext == "txt":
        return 1
    from pypdf import PdfReader
    try:
        return len(PdfReader(stream).pages)
    except Exception:
        raise ValueError("Could not read this PDF (corrupt or encrypted).")
