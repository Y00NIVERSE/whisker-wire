"""The PDF text reader, tested on PDFs built byte by byte here (there is no PDF library in this project, by design),
covering the encodings real results announcements use, and the hostile cases: encrypted, scanned, and zip bombs."""
import sys
import unittest
import zlib
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdftext  # noqa: E402


def stream(extra, content, compress=True):
    data = zlib.compress(content) if compress else content
    d = b"<< " + extra + b" /Length " + str(len(data)).encode() + (b" /Filter /FlateDecode" if compress else b"") + b" >>"
    return d + b"\nstream\n" + data + b"\nendstream"


def build(objs, header=b"%PDF-1.5\n", trailer=b"<< /Root 1 0 R >>"):
    out = bytearray(header)
    for num, body in objs.items():
        out += str(num).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    out += b"trailer\n" + trailer + b"\n%%EOF"
    return bytes(out)


def one_page(content, font=b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>", compress=True, extra=None):
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>", 2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            3: b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            4: font, 5: stream(b"", content, compress)}
    objs.update(extra or {})
    return build(objs)


PARA = b"Revenue rose 12% to $4.2 billion in the quarter compared with last year, helped by strong demand. " * 3


class SimpleText(unittest.TestCase):
    def test_lines_come_from_text_positioning(self):
        pdf = one_page(b"BT /F1 12 Tf 72 700 Td (Acme Corp Reports Results) Tj 0 -14 Td (Revenue rose 12 percent) Tj ET " + b"BT /F1 12 Tf 72 600 Td (" + PARA + b") Tj ET")
        lines = pdftext.extract(pdf)
        self.assertEqual(lines[0], "Acme Corp Reports Results")
        self.assertEqual(lines[1], "Revenue rose 12 percent")

    def test_words_positioned_apart_get_a_space_and_kerning_does_not(self):
        pdf = one_page(b"BT /F1 12 Tf 72 700 Td [(Rev) 20 (enue) -300 (rose) -300 (12)] TJ ET BT /F1 12 Tf 72 600 Td (" + PARA + b") Tj ET")
        self.assertEqual(pdftext.extract(pdf)[0], "Revenue rose 12")

    WIDTHS = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding /FirstChar 32 /LastChar 126 /Widths [" + b" ".join([b"500"] * 95) + b"] >>"

    def test_chunks_that_touch_are_one_word_and_chunks_with_a_gap_are_two(self):
        # each Tm places a chunk; 12pt at 500/1000 em = 6pt per letter, so "fin" ends at x=118 and "ancial" at 118 touches it
        touching = b"BT /F1 12 Tf 1 0 0 1 100 700 Tm (fin) Tj 1 0 0 1 118 700 Tm (ancial) Tj ET "
        apart = b"BT /F1 12 Tf 1 0 0 1 100 650 Tm (fin) Tj 1 0 0 1 130 650 Tm (ancial) Tj ET "
        pdf = one_page(touching + apart + b"BT /F1 12 Tf 72 500 Td (" + PARA + b") Tj ET", font=self.WIDTHS)
        lines = pdftext.extract(pdf)
        self.assertEqual(lines[0], "financial")
        self.assertEqual(lines[1], "fin ancial")

    def test_text_blocks_that_continue_a_line_are_not_new_lines(self):
        # the second BT..ET block starts again from the origin; it is still on the same baseline at the next x
        pdf = one_page(b"BT /F1 12 Tf 100 700 Td (su) Tj ET BT /F1 12 Tf 112 700 Td (bstantial) Tj ET BT /F1 12 Tf 100 600 Td (" + PARA + b") Tj ET", font=self.WIDTHS)
        self.assertEqual(pdftext.extract(pdf)[0], "substantial")

    def test_type0_widths_come_from_dw_and_the_w_array(self):
        cmap = (b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CMapName /X def 1 begincodespacerange <0000> <FFFF> endcodespacerange "
                b"1 beginbfrange <0001> <0005> <0061> endbfrange endcmap end end")
        font = (b"<< /Type /Font /Subtype /Type0 /BaseFont /X /Encoding /Identity-H /ToUnicode 6 0 R /DescendantFonts [7 0 R] >>")
        desc = b"<< /Type /Font /Subtype /CIDFontType2 /DW 500 /W [1 [600] 2 3 500] >>"
        body = b"".join([b"BT /F1 12 Tf 72 %d Td <000100020003000400050001> Tj ET " % (500 - i * 14) for i in range(20)])
        # <0001> is 600 wide: "a" at 72 ends at 79.2; the next chunk at 79.2 touches, at 90 does not
        touch = b"BT /F1 12 Tf 1 0 0 1 72 700 Tm <0001> Tj 1 0 0 1 79.2 700 Tm <0002> Tj ET "
        apart = b"BT /F1 12 Tf 1 0 0 1 72 650 Tm <0001> Tj 1 0 0 1 90 650 Tm <0002> Tj ET "
        pdf = one_page(touch + apart + body, font=font, extra={6: stream(b"", cmap), 7: desc})
        lines = pdftext.extract(pdf)
        self.assertEqual(lines[0], "ab")
        self.assertEqual(lines[1], "a b")

    def test_a_hyphen_placed_on_its_own_is_joined(self):
        pdf = one_page(b"BT /F1 12 Tf 72 700 Td (best) Tj 3 0 Td (-) Tj 6 0 Td (selling) Tj ET BT /F1 12 Tf 72 600 Td (" + PARA + b") Tj ET", font=self.WIDTHS)
        self.assertEqual(pdftext.extract(pdf)[0], "best-selling")

    def test_uncompressed_streams_and_escapes(self):
        pdf = one_page(b"BT /F1 12 Tf 72 700 Td (Profit \\(net\\) was \\$5 million \\101) Tj ET BT /F1 12 Tf 72 600 Td (" + PARA + b") Tj ET", compress=False)
        self.assertEqual(pdftext.extract(pdf)[0], "Profit (net) was $5 million A")

    def test_winansi_punctuation_decodes(self):
        pdf = one_page(b"BT /F1 12 Tf 72 700 Td (The Company\x92s results \x96 up 5\x95) Tj ET BT /F1 12 Tf 72 600 Td (" + PARA + b") Tj ET")
        self.assertEqual(pdftext.extract(pdf)[0], "The Company’s results – up 5•")

    def test_a_differences_table_maps_codes_to_named_glyphs(self):
        font = b"<< /Type /Font /Subtype /Type1 /Encoding << /Type /Encoding /Differences [65 /fi /fl /bullet] >> >>"
        pdf = one_page(b"BT /F1 12 Tf 72 700 Td (ABC) Tj ET BT /F1 12 Tf 72 600 Td (" + PARA + b") Tj ET", font=font)
        self.assertEqual(pdftext.extract(pdf)[0], "ﬁﬂ•".replace("ﬁ", "fi").replace("ﬂ", "fl"))

    def test_pages_are_read_in_the_order_of_the_page_tree(self):
        objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>", 2: b"<< /Type /Pages /Kids [4 0 R 3 0 R] /Count 2 >>",
                3: b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 6 0 R >> >> /Contents 5 0 R >>",
                4: b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 6 0 R >> >> /Contents 7 0 R >>",
                5: stream(b"", b"BT /F1 12 Tf 72 700 Td (SECOND page " + PARA + b") Tj ET"),
                6: b"<< /Type /Font /Subtype /Type1 /Encoding /WinAnsiEncoding >>",
                7: stream(b"", b"BT /F1 12 Tf 72 700 Td (FIRST page " + PARA + b") Tj ET")}
        lines = [ln for ln in pdftext.extract(build(objs)) if ln]
        self.assertTrue(lines[0].startswith("FIRST page") and lines[1].startswith("SECOND page"))


class ToUnicodeFonts(unittest.TestCase):
    CMAP = (b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CMapName /X def 1 begincodespacerange <0000> <FFFF> endcodespacerange "
            b"2 beginbfchar <0001> <0052> <0002> <0065> endbfchar 1 beginbfrange <0003> <0005> <0076> endbfrange endcmap end end")

    def test_a_type0_font_with_a_tounicode_table_is_read_from_hex_codes(self):
        # codes 1,2,3,4,5 -> R e v w x ; "Revw" is enough to prove the table is used
        font = b"<< /Type /Font /Subtype /Type0 /BaseFont /X /Encoding /Identity-H /ToUnicode 6 0 R >>"
        pdf = one_page(b"BT /F1 12 Tf 72 700 Td <00010002000300040005> Tj ET BT /F1 12 Tf 72 600 Td <00010002> Tj ET " + b"".join([b"BT /F1 12 Tf 72 %d Td <000100020003000400050001> Tj ET " % (500 - i * 14) for i in range(20)]),
                       font=font, extra={6: stream(b"", self.CMAP)})
        lines = pdftext.extract(pdf)
        self.assertEqual(lines[0], "Revwxy"[:5] if False else "Revwx")
        self.assertEqual(lines[1], "Re")

    def test_a_type0_font_with_no_table_cannot_be_read_and_says_so(self):
        font = b"<< /Type /Font /Subtype /Type0 /BaseFont /X /Encoding /Identity-H >>"
        pdf = one_page(b"".join([b"BT /F1 12 Tf 72 %d Td <000100020003000400050001> Tj ET " % (700 - i * 14) for i in range(30)]), font=font)
        with self.assertRaises(pdftext.PdfError) as cm:
            pdftext.extract(pdf)
        self.assertIn("encoding", str(cm.exception))


class Structure(unittest.TestCase):
    def test_objects_packed_in_an_object_stream_are_found(self):
        inner = [(1, b"<< /Type /Catalog /Pages 2 0 R >>"), (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
                 (3, b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"),
                 (4, b"<< /Type /Font /Subtype /Type1 /Encoding /WinAnsiEncoding >>")]
        body, header, off = b"", b"", 0
        for num, b in inner:
            header += f"{num} {off} ".encode()
            body += b + b"\n"
            off += len(b) + 1
        objstm = stream(f"/Type /ObjStm /N {len(inner)} /First {len(header)}".encode(), header + body)
        pdf = build({10: objstm, 5: stream(b"", b"BT /F1 12 Tf 72 700 Td (Packed objects work " + PARA + b") Tj ET")}, trailer=b"<< /Root 1 0 R >>")
        self.assertTrue(pdftext.extract(pdf)[0].startswith("Packed objects work"))

    def test_a_png_predictor_on_an_object_stream_is_undone(self):
        raw = b"3 0 << /A 1 >>"
        # one row, "Up" filter over a zero previous row = the bytes themselves
        rows = bytes([2]) + raw[:len(raw)]
        out = pdftext._predict(rows, {"Predictor": 12, "Columns": len(raw)}, pdftext.Doc(one_page(b"BT ET")))
        self.assertEqual(out, raw)

    def test_a_missing_page_tree_still_finds_the_pages(self):
        objs = {3: b"<< /Type /Page /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
                4: b"<< /Type /Font /Subtype /Type1 /Encoding /WinAnsiEncoding >>",
                5: stream(b"", b"BT /F1 12 Tf 72 700 Td (No catalog needed " + PARA + b") Tj ET")}
        self.assertTrue(pdftext.extract(build(objs))[0].startswith("No catalog needed"))

    def test_text_shown_with_quote_operators_and_t_star(self):
        pdf = one_page(b"BT /F1 12 Tf 14 TL 72 700 Td (First line) Tj T* (Second line) Tj (Third line) ' ET BT /F1 12 Tf 72 500 Td (" + PARA + b") Tj ET")
        self.assertEqual(pdftext.extract(pdf)[:3], ["First line", "Second line", "Third line"])

    def test_an_inline_image_is_skipped_not_misread(self):
        pdf = one_page(b"BT /F1 12 Tf 72 700 Td (Before) Tj ET q BI /W 2 /H 2 ID \x00\x01(garbage)Tj\xff EI Q BT /F1 12 Tf 72 600 Td (After " + PARA + b") Tj ET")
        text = " ".join(pdftext.extract(pdf))
        self.assertIn("Before", text)
        self.assertNotIn("garbage", text)


class GoogleLinksAndTheReader(unittest.TestCase):
    def test_google_wrappers_are_unwrapped(self):
        import engine
        n = engine.normalize_link
        self.assertEqual(n("https://www.google.com/url?sa=t&url=https%3A%2F%2Fex.com%2Fa.pdf&usg=x"), "https://ex.com/a.pdf")
        self.assertEqual(n("https://www.google.com/url?q=https://ex.com/b.pdf&sa=U"), "https://ex.com/b.pdf")
        self.assertEqual(n("https://docs.google.com/viewer?url=https%3A%2F%2Fex.com%2Fc.pdf&embedded=true"), "https://ex.com/c.pdf")
        self.assertEqual(n("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing"), "https://drive.google.com/uc?export=download&id=1AbCdEfGhIjKlMnOp")
        self.assertEqual(n("https://drive.google.com/open?id=1AbCdEfGhIjKlMnOp"), "https://drive.google.com/uc?export=download&id=1AbCdEfGhIjKlMnOp")

    def test_everything_else_is_left_alone_and_a_wrapper_cannot_smuggle_another_scheme(self):
        import engine
        n = engine.normalize_link
        self.assertEqual(n("https://example.com/report.pdf"), "https://example.com/report.pdf")
        self.assertEqual(n("https://www.google.com/search?q=dbs+results"), "https://www.google.com/search?q=dbs+results")
        self.assertEqual(n("https://www.google.com/url?q=file:///etc/passwd"), "https://www.google.com/url?q=file:///etc/passwd")
        self.assertEqual(n("https://www.google.com/url?q=javascript:alert(1)"), "https://www.google.com/url?q=javascript:alert(1)")

    def test_the_article_reader_reads_a_pdf_and_gives_it_a_title(self):
        import engine
        pdf = one_page(b"BT /F1 12 Tf 72 700 Td (Acme Corp Reports Second Quarter Results) Tj ET BT /F1 12 Tf 72 680 Td (" + PARA + b") Tj ET")
        with mock.patch.object(engine, "http_get", return_value=(pdf, "utf-8")):
            a = engine.get_article("https://example.com/results.pdf")
        self.assertEqual(a["title"], "Acme Corp Reports Second Quarter Results")
        self.assertTrue(any("Revenue rose 12%" in p for p in a["paragraphs"]))

    def test_web_pages_keep_their_old_size_limit_but_a_pdf_may_be_large(self):
        import engine
        page = b"<html><body>" + b"<p>Revenue rose strongly in the quarter, the company said on a call with analysts today.</p>" * 40 + b"</body></html>"
        with mock.patch.object(engine, "http_get", return_value=(page + b" " * 3_000_000, "utf-8")):
            self.assertTrue(engine.get_article("https://example.com/news")["paragraphs"])

    def test_pdf_lines_are_joined_into_sentences_and_split_words_are_repaired(self):
        from textutil import unwrap_lines
        out = unwrap_lines(["The Committee judged that the Sys-", "tem should continue to reduce its holdings and the", "balance sheet.", "", "Next paragraph starts here."])
        self.assertEqual(out[0], "The Committee judged that the System should continue to reduce its holdings and the balance sheet.")
        self.assertEqual(out[1], "Next paragraph starts here.")

    def test_a_real_hyphenated_compound_is_left_alone(self):
        from textutil import unwrap_lines
        self.assertEqual(unwrap_lines(["a year-", "Over-year comparison."])[0], "a year- Over-year comparison.")


class HostileAndBroken(unittest.TestCase):
    def test_not_a_pdf(self):
        with self.assertRaises(pdftext.PdfError):
            pdftext.extract(b"<html>nope</html>")

    def test_an_encrypted_pdf_is_declined_with_the_way_forward(self):
        pdf = build({1: b"<< /Type /Catalog /Pages 2 0 R >>", 2: b"<< /Type /Pages /Kids [] /Count 0 >>"}, trailer=b"<< /Root 1 0 R /Encrypt 9 0 R >>")
        with self.assertRaises(pdftext.PdfError) as cm:
            pdftext.extract(pdf)
        self.assertIn("password", str(cm.exception))
        self.assertIn("paste", str(cm.exception))

    def test_a_scan_with_no_text_says_so(self):
        pdf = one_page(b"q 612 0 0 792 0 0 cm /Im0 Do Q")
        with self.assertRaises(pdftext.PdfError) as cm:
            pdftext.extract(pdf)
        self.assertIn("scan", str(cm.exception))

    def test_a_stream_that_inflates_past_the_cap_is_refused(self):
        bomb = stream(b"", b"A" * 200_000)
        pdf = one_page(b"BT ET", extra={5: bomb})
        with mock.patch.object(pdftext, "MAX_STREAM", 10_000):
            with self.assertRaises(pdftext.PdfError) as cm:
                pdftext.extract(pdf)
        self.assertIn("too large", str(cm.exception))

    def test_an_oversized_file_is_refused_before_parsing(self):
        with mock.patch.object(pdftext, "MAX_BYTES", 1000):
            with self.assertRaises(pdftext.PdfError):
                pdftext.extract(b"%PDF-1.4\n" + b"x" * 2000)

    def test_a_damaged_flate_stream_keeps_what_it_can(self):
        good = zlib.compress(b"BT /F1 12 Tf 72 700 Td (Salvaged " + PARA + b") Tj ET")
        broken = good[:-6] + b"\x00\x00\x00"
        pdf = one_page(b"", extra={5: b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(broken) + broken + b"\nendstream"})
        self.assertTrue(pdftext.extract(pdf)[0].startswith("Salvaged"))

    def test_garbage_between_objects_does_not_crash_the_scan(self):
        pdf = b"%PDF-1.4\n" + b"\x00\xff garbage 9999999999 0 obj << unterminated " + one_page(b"BT /F1 12 Tf 72 700 Td (Still found " + PARA + b") Tj ET")[9:]
        self.assertTrue(pdftext.extract(pdf)[0].startswith("Still found"))

    def test_deeply_nested_arrays_are_refused_not_recursed_forever(self):
        pdf = build({1: b"[" * 5000 + b"]" * 5000})
        with self.assertRaises(pdftext.PdfError):
            pdftext.Doc(pdf)._scan if False else pdftext.extract(pdf)


if __name__ == "__main__":
    unittest.main()
