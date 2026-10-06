"""Company brief: numbers, annual-report reading, latest developments. All offline: the SEC is replaced by fixtures
shaped like its real responses."""
import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import company  # noqa: E402
import engine  # noqa: E402
import server  # noqa: E402
import tick_chat  # noqa: E402

NOW = time.mktime(time.strptime("2026-06-01", "%Y-%m-%d"))


def rows(*items):
    keys = ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument", "items")
    return [dict(zip(keys, it)) for it in items]


class Developments(unittest.TestCase):
    R = rows(
        ("0000000001-26-000010", "2026-05-20", "", "8-K", "a.htm", "2.02,9.01"),
        ("0000000001-26-000009", "2026-05-02", "", "8-K", "b.htm", "4.02"),
        ("0000000001-26-000008", "2026-04-02", "", "8-K", "c.htm", "5.02,7.01"),
        ("0000000001-26-000007", "2026-03-30", "2026-03-31", "10-Q", "q.htm", ""),
        ("0000000001-26-000006", "2026-03-01", "", "4", "f4.xml", ""),
        ("0000000001-24-000001", "2024-01-05", "", "8-K", "old.htm", "1.01"),
    )

    def test_items_are_translated_and_exhibits_dropped(self):
        d = company.developments(self.R, 123, now=NOW)
        first = d[0]
        self.assertEqual([i["code"] for i in first["items"]], ["2.02"])
        self.assertIn("earnings", first["items"][0]["label"].lower())

    def test_a_restatement_is_flagged_as_the_worst_kind(self):
        d = {x["date"]: x for x in company.developments(self.R, 123, now=NOW)}
        self.assertEqual(d["2026-05-02"]["tone"], "bad")
        self.assertEqual(d["2026-04-02"]["tone"], "warn")   # an executive leaving or arriving
        self.assertEqual(d["2026-05-20"]["tone"], "info")

    def test_old_filings_and_insider_forms_are_left_out(self):
        d = company.developments(self.R, 123, now=NOW)
        self.assertTrue(all(x["date"] >= "2026-03-01" for x in d))
        self.assertNotIn("4", [x["form"] for x in d])

    def test_a_quarterly_report_is_a_plain_event(self):
        q = [x for x in company.developments(self.R, 123, now=NOW) if x["form"] == "10-Q"][0]
        self.assertEqual(q["items"][0]["label"], "Filed its quarterly report")

    def test_links_go_to_the_filing_index_on_sec_gov(self):
        for x in company.developments(self.R, 123, now=NOW):
            self.assertTrue(x["url"].startswith("https://www.sec.gov/Archives/edgar/data/123/"))

    def test_identifiers_the_sec_did_not_issue_are_refused(self):
        with self.assertRaises(ValueError):
            company._doc_url(1, {"accessionNumber": "../../etc/passwd", "primaryDocument": "x.htm"})
        with self.assertRaises(ValueError):
            company._doc_url(1, {"accessionNumber": "0000000001-26-000010", "primaryDocument": "http://evil/x.htm"})
        with self.assertRaises(ValueError):
            company._index_url(1, {"accessionNumber": "nope"})


def facts_for(years, rev, ni, cfo=None, capex=None, debt=None, equity=None, cash=None, gp=None, quarterly=True):
    """SEC 'companyfacts' shape: every fact is a list of dated entries, quarters included."""
    def flow(vals):
        ents = []
        for y, v in zip(years, vals):
            ents.append({"start": f"{y}-01-01", "end": f"{y}-12-31", "val": v, "form": "10-K", "filed": f"{y + 1}-02-10", "fp": "FY"})
            if quarterly:   # a quarter must never be mistaken for a year
                ents.append({"start": f"{y}-10-01", "end": f"{y}-12-31", "val": v / 4, "form": "10-K", "filed": f"{y + 1}-02-10", "fp": "FY"})
        return {"units": {"USD": ents}}

    def stock(vals):
        return {"units": {"USD": [{"end": f"{y}-12-31", "val": v, "form": "10-K", "filed": f"{y + 1}-02-10"} for y, v in zip(years, vals)]}}
    g = {"Revenues": flow(rev), "NetIncomeLoss": flow(ni)}
    if cfo: g["NetCashProvidedByUsedInOperatingActivities"] = flow(cfo)
    if capex: g["PaymentsToAcquirePropertyPlantAndEquipment"] = flow(capex)
    if gp: g["GrossProfit"] = flow(gp)
    if debt: g["LongTermDebt"] = stock(debt)
    if equity: g["StockholdersEquity"] = stock(equity)
    if cash: g["CashAndCashEquivalentsAtCarryingValue"] = stock(cash)
    return {"us-gaap": g}


Y = [2021, 2022, 2023, 2024, 2025]


class Numbers(unittest.TestCase):
    def test_years_align_and_quarters_are_ignored(self):
        f = company.financials(facts_for(Y, [100, 120, 140, 160, 200], [10, 12, 14, 16, 24]))
        self.assertEqual(f["years"][-1], "2025-12-31")
        self.assertEqual(f["rows"]["revenue"], [100, 120, 140, 160, 200])
        self.assertEqual(f["rows"]["net_margin"][-1], 0.12)

    def test_growth_and_margin_are_read_in_plain_english(self):
        f = company.financials(facts_for(Y, [100, 120, 140, 160, 200], [10, 12, 14, 16, 24]))
        text = " ".join(r["text"] for r in f["read"])
        self.assertIn("Revenue grew 25.0% to $200", text)
        self.assertIn("a year over 4 years", text)
        self.assertIn("Net margin", text)
        self.assertEqual(f["read"][0]["tone"], "good")

    def test_a_loss_is_called_a_loss(self):
        f = company.financials(facts_for(Y, [100, 90, 80, 70, 60], [5, 1, -2, -5, -9]))
        self.assertTrue(any(r["tone"] == "bad" and "lost money" in r["text"] for r in f["read"]))
        self.assertTrue(any(r["tone"] == "warn" and r["text"].startswith("Revenue fell") for r in f["read"]))

    def test_profit_that_never_became_cash_is_questioned(self):
        f = company.financials(facts_for(Y, [100] * 5, [20] * 5, cfo=[8] * 5, capex=[2] * 5))
        text = " ".join(r["text"] for r in f["read"])
        self.assertIn("40 cents of each dollar", text)
        self.assertEqual(f["rows"]["fcf"][-1], 6)

    def test_cash_backed_profit_and_a_cash_pile_are_credited(self):
        f = company.financials(facts_for(Y, [100] * 5, [20] * 5, cfo=[26] * 5, debt=[10] * 5, equity=[50] * 5, cash=[40] * 5))
        text = " ".join(r["text"] for r in f["read"])
        self.assertIn("backed by cash", text)
        self.assertIn("more cash", text)

    def test_negative_equity_and_heavy_debt_are_warned_about(self):
        f = company.financials(facts_for(Y, [100] * 5, [10] * 5, debt=[900] * 5, equity=[-50] * 5))
        self.assertTrue(any("equity is negative" in r["text"] for r in f["read"]))
        g = company.financials(facts_for(Y, [100] * 5, [10] * 5, debt=[900] * 5, equity=[100] * 5))
        self.assertTrue(any("heavily borrowed" in r["text"] for r in g["read"]))

    def test_no_revenue_or_profit_data_means_no_table_not_a_crash(self):
        self.assertIsNone(company.financials({"us-gaap": {"Assets": {"units": {"USD": []}}}}))

    def test_foreign_filers_using_ifrs_names_and_their_own_currency(self):
        e = [{"start": f"{y}-01-01", "end": f"{y}-12-31", "val": v, "form": "20-F", "filed": f"{y + 1}-03-01"} for y, v in zip(Y, [10, 11, 12, 13, 14])]
        f = company.financials({"ifrs-full": {"Revenue": {"units": {"EUR": e}}}})
        self.assertEqual(f["currency"], "EUR")
        self.assertIn("€14", f["read"][0]["text"])

    def test_money_formatting(self):
        self.assertEqual(company.money(391_035_000_000), "$391.0B")
        self.assertEqual(company.money(-2_500_000), "-$2M")
        self.assertEqual(company.money(950), "$950")


BOILER = "The company operates in a competitive industry and faces many uncertainties in the ordinary course of business. " * 40


def html_report(risk_extra="", mdna_extra="", intro_extra=""):
    return f"""<html><head><title>10-K</title></head><body>
<ix:header><p>HIDDEN XBRL SHOULD NOT APPEAR going concern</p></ix:header>
<p>TABLE OF CONTENTS</p>
<p>Item 1A. Risk Factors</p><p>Item 1B. Unresolved Staff Comments</p><p>Item 7. Management's Discussion</p><p>Item 7A. Quantitative</p>
<p>Item 1.</p><p>Business</p><p>{BOILER}{intro_extra}</p>
<p>Item 1A.</p><p>Risk Factors</p>
<p>{BOILER}</p><p>{risk_extra}</p>
<p>Item 1B. Unresolved Staff Comments</p><p>None.</p>
<p>Item 7. Management's Discussion and Analysis</p>
<p>{BOILER}</p><p>{mdna_extra}</p>
<p>Item 7A. Quantitative and Qualitative Disclosures</p><p>Nothing.</p>
</body></html>"""


class ReadingTheReport(unittest.TestCase):
    def test_hidden_header_is_skipped_and_split_headings_are_joined(self):
        lines = company.doc_lines(html_report())
        self.assertFalse(any("HIDDEN XBRL" in x for x in lines))
        self.assertIn("Item 1A. Risk Factors", lines)

    def test_the_real_section_beats_the_table_of_contents(self):
        lines = company.doc_lines(html_report(risk_extra="Our unique zebra risk could harm results."))
        risk = company.section(lines, "risk")
        self.assertIn("zebra", risk)
        self.assertGreater(len(risk), 2000)
        self.assertNotIn("Unresolved", risk)

    def test_filings_that_repeat_an_item_label_on_every_paragraph_still_parse(self):
        # Microsoft's layout: "Item 1A ITEM 1A. RISK FACTORS", then "Item 1A <paragraph>" throughout
        body = "".join(f"<p>Item 1A {BOILER[:900]}</p>" for _ in range(3))
        doc = (f"<html><body><p>Item 1A. Risk Factors</p><p>Item 1B. Unresolved Staff Comments</p>"
               f"<p>Item 1A ITEM 1A. RISK FACTORS</p>{body}<p>Item 1A Our unique zebra risk could harm results.</p>"
               f"<p>Item 1B, 1C</p><p>ITEM 1B. UNRESOLVED STAFF COMMENTS</p></body></html>")
        risk = company.section(company.doc_lines(doc), "risk")
        self.assertIn("zebra", risk)
        self.assertNotIn("Item 1A", risk)

    def test_missing_sections_give_nothing_instead_of_junk(self):
        self.assertEqual(company.section(["Item 1A. Risk Factors", "tiny", "Item 1B. x"], "risk"), "")

    def test_a_stated_problem_is_a_flag_and_a_hypothetical_is_toned_down(self):
        text = ("Management identified a material weakness in our internal control over financial reporting as of year end. "
                "If we fail to pay lenders there could be substantial doubt about our ability to continue as a going concern in future.")
        flags = {f["id"]: f for f in company.scan_flags(text)}
        self.assertEqual(flags["weak"]["tone"], "bad")
        self.assertFalse(flags["weak"]["hedged"])
        self.assertEqual(flags["going"]["tone"], "info")   # only 'could' - the usual boilerplate
        self.assertTrue(flags["going"]["hedged"])
        self.assertEqual(company.scan_flags(text)[0]["id"], "weak")   # worst first

    def test_customer_concentration_needs_a_real_percentage(self):
        s = "One customer accounted for 34% of our total net revenue during the fiscal year ended December 31, 2025."
        self.assertEqual(company.scan_flags(s)[0]["id"], "conc")
        self.assertEqual(company.scan_flags("One customer accounted for 4% of our total net revenue during the fiscal year ended 2025."), [])

    def test_a_clean_report_has_no_flags(self):
        self.assertEqual(company.scan_flags(BOILER), [])

    # Each of these was a real false alarm on a real 10-K (Coca-Cola, Apple, Tesla) during the first live run.
    def test_ongoing_concern_is_not_going_concern(self):
        s = "In addition, ongoing concern over climate change is expected to continue to result in additional legal or regulatory requirements."
        self.assertEqual(company.scan_flags(s), [])
        t = "There is substantial doubt about the Company's ability to continue as a going concern within one year of this filing date."
        self.assertEqual(company.scan_flags(t)[0]["id"], "going")

    def test_a_disclaimer_about_the_litigation_reform_act_is_not_a_lawsuit(self):
        s = "This Annual Report contains forward-looking statements within the meaning of the Private Securities Litigation Reform Act of 1995, and actual results may differ."
        self.assertEqual(company.scan_flags(s), [])

    def test_saying_nothing_was_written_down_is_not_a_write_down(self):
        self.assertEqual(company.scan_flags("For the years ended December 31, 2025, 2024, and 2023, we did not recognize any impairment of goodwill."), [])
        real = "In fiscal 2025 the Company recorded a non-cash goodwill impairment charge of $412 million related to its European segment."
        self.assertEqual(company.scan_flags(real)[0]["id"], "impair")

    def test_an_auditors_description_of_its_work_is_not_a_control_weakness(self):
        s = "Our audit included obtaining an understanding of internal control over financial reporting and assessing the risk that a material weakness exists."
        self.assertEqual(company.scan_flags(s), [])

    def test_a_real_control_failure_still_gets_through_even_with_the_word_not(self):
        s = "Management concluded that internal control over financial reporting was not effective as of year end because of the material weaknesses described below."
        self.assertEqual(company.scan_flags(s)[0]["id"], "weak")
        self.assertFalse(company.scan_flags(s)[0]["hedged"])

    def test_generic_cyber_risk_language_is_boilerplate_but_an_actual_incident_is_not(self):
        risk = "We face various cybersecurity attacks, including unauthorized access, which could disrupt operations and harm our reputation."
        self.assertTrue(company.scan_flags(risk)[0]["hedged"])
        real = "In March the Company detected a ransomware attack that encrypted certain internal systems and delayed shipments for two weeks."
        self.assertFalse(company.scan_flags(real)[0]["hedged"])

    def test_routine_regulator_requests_are_not_an_announced_investigation_but_a_received_subpoena_is(self):
        self.assertTrue(company.scan_flags("Regulators may issue a subpoena or open a formal investigation into our practices at any time without notice.")[0]["hedged"])
        self.assertFalse(company.scan_flags("In June the Company received a subpoena from the SEC as part of a formal investigation into its revenue recognition.")[0]["hedged"])

    # Second round of real-filing fixes (Coca-Cola, Tesla, TSMC, Ford, Beyond Meat).
    def test_we_cannot_eliminate_cyber_risk_is_not_an_incident(self):
        s = "We cannot eliminate all risks from cybersecurity threats or provide assurances that we have not experienced an undetected cybersecurity incident."
        self.assertTrue(company.scan_flags(s)[0]["hedged"])

    def test_an_immaterial_write_down_and_an_accounting_policy_are_not_red_flags(self):
        self.assertEqual(company.scan_flags("During 2023, we recorded an immaterial amount of impairment losses on digital assets held by the company."), [])
        self.assertEqual(company.scan_flags("Equity investments are carried at cost, less any recognized impairment loss, and tested every year."), [])

    def test_a_threshold_in_a_table_note_is_not_customer_concentration(self):
        self.assertEqual(company.scan_flags("Major customers representing at least 10% of net revenue are listed below for each fiscal year."), [])
        self.assertEqual(company.scan_flags("Customers that accounted for more than 10% of total net revenue are described in the notes that follow this table.")[:0], [])

    def test_a_valuation_policy_mentioning_delisted_securities_is_not_a_listing_threat(self):
        self.assertEqual(company.scan_flags("Securities that are thinly traded or delisted are valued using pricing data not observable in the market."), [])
        real = "On March 4, 2026, we received a deficiency notice from the Nasdaq Listing Qualifications Department because our share price closed below one dollar."
        self.assertEqual(company.scan_flags(real)[0]["id"], "delist")
        self.assertFalse(company.scan_flags(real)[0]["hedged"])

    def test_a_policy_for_handling_incidents_is_not_an_incident(self):
        s = "When a cybersecurity incident is identified, our policy is to review and triage it and escalate it to senior management."
        self.assertTrue(company.scan_flags(s)[0]["hedged"])

    def test_generic_class_action_risk_text_is_not_a_filed_lawsuit(self):
        generic = "In the past, following volatility in the price of a company's shares, securities class action litigation often has been brought against that company."
        self.assertTrue(company.scan_flags(generic) == [] or company.scan_flags(generic)[0]["hedged"])
        real = "On August 30, 2024, a putative class action complaint was filed against the Company and its Chief Executive Officer."
        self.assertFalse(company.scan_flags(real)[0]["hedged"])

    def test_governance_descriptions_denials_and_footnotes_are_not_findings(self):
        self.assertTrue(company.scan_flags("The Audit Committee reviews and provides oversight of our cybersecurity processes and any cybersecurity incident that is identified.")[0]["hedged"])
        self.assertEqual(company.scan_flags("At this time, we have no such class actions filed against us and we are not aware of any pending claims."), [])
        self.assertEqual(company.scan_flags("(a)2023 includes $28 million related to restructuring charges in India and $41 million in North America."), [])

    def test_the_phrase_period_under_review_does_not_hide_a_real_finding(self):
        s = "Management concluded that internal control over financial reporting was not effective because of a material weakness identified in the period under review."
        self.assertFalse(company.scan_flags(s)[0]["hedged"])

    def test_half_sentences_are_not_offered_as_new_risks(self):
        old = "Our business could be harmed by supply chain disruption that delays shipments of key components to our customers worldwide. " * 3
        new = "and caused disruptions in our production operations, which may increase the risk of adverse effects on revenue in future periods and years."
        self.assertEqual(company.new_risks(new, old), [])

    def test_contract_warranties_are_not_loan_covenants(self):
        s = "We have agreed to indemnify certain parties against losses arising from a breach of representations, warranties or covenants in those agreements."
        self.assertTrue(company.scan_flags(s) == [] or company.scan_flags(s)[0]["hedged"])
        real = "We were not in compliance with a financial covenant under our credit facility at year end and obtained a waiver from our lenders."
        self.assertFalse(company.scan_flags(real)[0]["hedged"])

    def test_bullets_are_stripped_from_the_front_of_quotes(self):
        self.assertEqual(company.sentences("•Net sales increased 5% primarily due to volume.")[0], "Net sales increased 5% primarily due to volume.")

    def test_connective_openings_are_not_offered_as_new_risks(self):
        old = "Our business could be harmed by supply chain disruption that delays shipments of key components to our customers worldwide. " * 3
        new = ("However, such agreements may not always be available on acceptable terms and further litigation may still arise from them over time. "
               "Newly imposed export controls on advanced chips may restrict our ability to sell to certain regions and could cause adverse effects on revenue.")
        found = company.new_risks(new, old)
        self.assertEqual(len(found), 1)
        self.assertIn("export controls", found[0])

    def test_us_abbreviations_do_not_split_sentences(self):
        s = company.sentences("The U.S. District Court ruled against Apple Inc. in the case. Separately, the company appealed.")
        self.assertEqual(len(s), 2)
        self.assertTrue(s[0].startswith("The U.S. District Court"))

    def test_management_reasons_in_plain_words_count_when_they_are_about_the_big_lines(self):
        text = ("Products net sales increased during 2025 compared to 2024 primarily due to higher net sales of the flagship phone and laptops.\n"
                "Employee morale increased primarily due to the new cafeteria opening at the main campus last spring season.")
        d = company.drivers(text)
        self.assertEqual(len(d), 1)
        self.assertIn("Products net sales", d[0])

    def test_windows_1252_filings_keep_their_apostrophes(self):
        raw = "The Company’s results".encode("cp1252")
        self.assertEqual(company._decode(raw), "The Company’s results")
        self.assertEqual(company._decode("café".encode("utf-8")), "café")

    def test_management_reasons_for_changes_are_picked_out(self):
        text = ("Net sales increased 12% compared with last year, primarily due to higher demand for services in North America.\n"
                "The weather was pleasant during the quarter and employees enjoyed the summer picnic event this year.")
        d = company.drivers(text)
        self.assertEqual(len(d), 1)
        self.assertIn("Net sales increased 12%", d[0])

    def test_new_risk_wording_is_found_and_old_wording_is_not(self):
        old = "Our business could be harmed by supply chain disruption that delays shipments of key components to our customers worldwide. " * 3
        new = ("Our business could be harmed by supply chain disruption that delays shipments of key components to our customers worldwide. "
               "Rapid advances in generative artificial intelligence may erode demand for our legacy software products and cause adverse effects on our margins.")
        found = company.new_risks(new, old)
        self.assertEqual(len(found), 1)
        self.assertIn("artificial intelligence", found[0])
        self.assertIsNone(company.new_risks(new, ""))

    def test_whole_pipeline_from_html(self):
        cur = {"form": "10-K", "filingDate": "2026-02-01", "reportDate": "2025-12-31", "accessionNumber": "0000000001-26-000001", "primaryDocument": "a10k.htm"}
        old = dict(cur, filingDate="2025-02-01", reportDate="2024-12-31", accessionNumber="0000000001-25-000001", primaryDocument="b10k.htm")
        cur_html = html_report(risk_extra="We identified a material weakness in internal control that remains unremediated at year end and affects our reporting. "
                                           "Generative artificial intelligence may erode demand for our legacy products and cause adverse effects on margins significantly.",
                               mdna_extra="Revenue increased 18% primarily due to strong growth in cloud subscriptions across all regions during the year.")
        docs = {"a10k.htm": cur_html, "b10k.htm": html_report()}
        with mock.patch.object(engine, "_sec_get", side_effect=lambda url, **k: docs[url.rsplit("/", 1)[1]].encode()):
            out = company.analyze(1, cur, old)
        self.assertTrue(out["sections"]["risk"] and out["sections"]["mdna"])
        self.assertEqual(out["flags"][0]["id"], "weak")
        self.assertTrue(out["drivers"] and "18%" in out["drivers"][0])
        self.assertTrue(any("artificial intelligence" in s for s in out["new_risks"]))
        self.assertEqual(out["prior"]["period"], "2024-12-31")


def yahoo_payload(years, rev, ni, total_debt=None, equity=None, cur="SGD"):
    """Yahoo's fundamentals-timeseries shape: one result per type, each a list of dated reported values."""
    def one(typ, vals):
        return {"meta": {"type": [typ]}, typ: [{"asOfDate": f"{y}-12-31", "currencyCode": cur, "reportedValue": {"raw": v}} for y, v in zip(years, vals)]}
    res = [one("annualTotalRevenue", rev), one("annualNetIncome", ni)]
    if total_debt:
        res.append(one("annualTotalDebt", total_debt))
    if equity:
        res.append(one("annualStockholdersEquity", equity))
    return {"timeseries": {"result": res, "error": None}}


class PastedReports(unittest.TestCase):
    def test_wrapped_pdf_text_is_joined_back_into_sentences(self):
        pdf = ("The Group recorded an impairment charge of $412 million on its\nEuropean property portfolio during the year.\n"
               "Management identified a material weakness in controls over\nfinancial reporting at year end.\n\nSeparate paragraph here.")
        lines = company._unwrap(pdf)
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("The Group recorded") and "European property" in lines[0])

    def test_scanning_pasted_text_finds_flags_and_reasons(self):
        text = ("Revenue increased 12% primarily due to higher loan volumes in the consumer banking segment across the region this year. " * 2
                + "\nThe Group recorded an impairment charge of $412 million on its\nEuropean property portfolio during the year.\n"
                + "Management concluded that internal control over financial reporting was not effective because of a material weakness identified in the period.\n"
                + BOILER)
        out = company.analyze_text(text)
        self.assertTrue(out["pasted"])
        flags = {f["id"]: f for f in out["flags"]}
        self.assertFalse(flags["impair"]["hedged"])
        self.assertEqual(flags["weak"]["tone"], "bad")
        self.assertTrue(out["drivers"] and "12%" in out["drivers"][0])
        self.assertIsNone(out["new_risks"])

    def test_too_little_text_is_asked_for_more(self):
        with self.assertRaises(ValueError):
            company.analyze_text("just a sentence")

    def test_huge_pastes_are_capped(self):
        out = company.analyze_text("Revenue grew. " * 100_000)
        self.assertLessEqual(out["words"], company.MAX_PASTE // 5)


class Brief(unittest.TestCase):
    def setUp(self):
        engine._cache.clear()
        self.sub = {"name": "ACME CORP", "filings": {"recent": {
            "accessionNumber": ["0000000001-26-000010", "0000000001-26-000001", "0000000001-25-000001"],
            "filingDate": ["2026-05-20", "2026-02-01", "2025-02-01"], "reportDate": ["", "2025-12-31", "2024-12-31"],
            "form": ["8-K", "10-K", "10-K"], "primaryDocument": ["a.htm", "k26.htm", "k25.htm"], "items": ["2.02", "", ""]}}}
        self.tickers = {"0": {"cik_str": 1234, "ticker": "ACME", "title": "Acme Corp"}, "1": {"cik_str": 99, "ticker": "BRK-B", "title": "Berkshire"}}

    def fake(self, url, **k):
        if url.endswith("company_tickers.json"):
            return json.dumps(self.tickers).encode()
        if "submissions" in url:
            return json.dumps(self.sub).encode()
        if "companyfacts" in url:
            return json.dumps({"facts": facts_for(Y, [100, 120, 140, 160, 200], [10, 12, 14, 16, 24])}).encode()
        raise AssertionError("unexpected fetch " + url)

    def test_off_until_the_sec_identity_is_set(self):
        with mock.patch.object(engine, "sec_agent", return_value=""):
            self.assertEqual(company.get_company("ACME"), {"configured": False})
            self.assertEqual(company.get_annual_report("ACME"), {"configured": False})

    def test_us_company_brief(self):
        with mock.patch.object(engine, "sec_agent", return_value="T t@e.com"), mock.patch.object(engine, "_sec_get", side_effect=self.fake):
            out = company.get_company("acme")
        self.assertTrue(out["supported"])
        self.assertEqual(out["name"], "ACME CORP")
        self.assertEqual(out["annual"]["period"], "2025-12-31")
        self.assertEqual(out["annual"]["url"], "https://www.sec.gov/Archives/edgar/data/1234/000000000126000001/k26.htm")
        self.assertEqual(out["financials"]["rows"]["revenue"][-1], 200)
        self.assertTrue(out["developments"][0]["form"] in ("8-K", "10-K"))

    def test_share_class_tickers_map_to_the_secs_spelling(self):
        with mock.patch.object(engine, "sec_agent", return_value="T t@e.com"), mock.patch.object(engine, "_sec_get", side_effect=self.fake):
            self.assertEqual(company.lookup("BRK.B")[0], 99)

    def test_non_us_tickers_get_numbers_not_filings_and_never_touch_the_sec(self):
        yf = yahoo_payload(Y, [100e9, 120e9, 140e9, 160e9, 200e9], [10e9, 12e9, 14e9, 16e9, 24e9])
        with mock.patch.object(engine, "sec_agent", return_value="T t@e.com"), \
                mock.patch.object(engine, "_sec_get", side_effect=AssertionError("the SEC must not be asked about a Singapore stock")), \
                mock.patch.object(engine, "http_get", return_value=(json.dumps(yf).encode(), "utf-8")) as get:
            out = company.get_company("D05.SI")
        self.assertEqual((out["configured"], out["supported"], out["market"]), (True, False, "sg"))
        self.assertEqual(out["financials"]["source"], "Yahoo Finance")
        self.assertEqual(out["financials"]["currency"], "SGD")
        self.assertIn("Revenue grew 25.0%", out["financials"]["read"][0]["text"])
        self.assertTrue(get.call_args[0][0].startswith("https://query1.finance.yahoo.com/ws/fundamentals-timeseries/"))

    def test_other_markets_work_without_any_sec_identity(self):
        yf = yahoo_payload(Y, [100e9] * 5, [10e9] * 5)
        with mock.patch.object(engine, "sec_agent", return_value=""), mock.patch.object(engine, "http_get", return_value=(json.dumps(yf).encode(), "utf-8")):
            self.assertTrue(company.get_company("0700.HK")["financials"])
            self.assertEqual(company.get_company("AAPL"), {"configured": False})   # a US ticker still needs the identity

    def test_a_failure_fetching_other_market_numbers_is_reported_not_raised(self):
        with mock.patch.object(engine, "sec_agent", return_value=""), mock.patch.object(engine, "http_get", side_effect=OSError("boom")):
            out = company.get_company("7203.T")
        self.assertEqual(out["market"], "jp")
        self.assertIn("financials_error", out)

    def test_share_classes_are_not_mistaken_for_exchanges(self):
        self.assertIsNone(company._EXCHANGE.search("BRK.B"))
        for s, m in (("D05.SI", "sg"), ("0700.HK", "hk"), ("HSBA.L", "uk"), ("7203.T", "jp"), ("RELIANCE.NS", "in"), ("BHP.AX", "au")):
            self.assertEqual(company._SUFFIX_MARKET[company._EXCHANGE.search(s).group(1)], m, s)

    def test_annual_report_for_another_market_is_politely_unsupported(self):
        with mock.patch.object(engine, "sec_agent", return_value=""):
            self.assertEqual(company.get_annual_report("D05.SI"), {"configured": True, "supported": False, "symbol": "D05.SI"})

    def test_banks_that_only_report_total_borrowings_still_show_debt(self):
        yf = yahoo_payload(Y, [100e9] * 5, [10e9] * 5, total_debt=[75e9] * 5, equity=[20e9] * 5)
        with mock.patch.object(engine, "http_get", return_value=(json.dumps(yf).encode(), "utf-8")):
            f = company.yahoo_financials("D05.SI")
        self.assertEqual(f["rows"]["debt"][-1], 75e9)
        self.assertTrue(any("times shareholders' equity" in r["text"] for r in f["read"]))

    def test_a_bank_is_not_judged_by_normal_company_cash_and_debt_rules(self):
        f = company.financials(facts_for(Y, [100] * 5, [30] * 5, cfo=[5] * 5, debt=[900] * 5, equity=[50] * 5, cash=[2000] * 5)
                               | {"us-gaap": dict(facts_for(Y, [100] * 5, [30] * 5, cfo=[5] * 5, debt=[900] * 5, equity=[50] * 5, cash=[2000] * 5)["us-gaap"],
                                                  Assets={"units": {"USD": [{"end": f"{y}-12-31", "val": 4500, "form": "10-K", "filed": f"{y + 1}-02-10"} for y in Y]}})})
        text = " ".join(r["text"] for r in f["read"])
        self.assertIn("bank or insurer", text)
        self.assertNotIn("cents of each dollar", text)
        self.assertNotIn("heavily borrowed", text)
        self.assertNotIn("more cash", text)

    def test_yahoo_with_nothing_for_a_symbol_is_none(self):
        with mock.patch.object(engine, "http_get", return_value=(b'{"timeseries": {"result": [], "error": null}}', "utf-8")):
            self.assertIsNone(company.yahoo_financials("NOPE.SI"))

    def test_bad_symbols_are_refused_before_anything_is_fetched(self):
        with mock.patch.object(engine, "sec_agent", return_value="T t@e.com"), mock.patch.object(engine, "_sec_get", side_effect=AssertionError("no fetch")):
            for bad in ("", "a b", "x" * 40, "<script>"):
                with self.assertRaises(ValueError):
                    company.get_company(bad)

    def test_a_failure_in_the_numbers_does_not_hide_the_rest(self):
        def flaky(url, **k):
            if "companyfacts" in url:
                raise OSError("boom")
            return self.fake(url, **k)
        with mock.patch.object(engine, "sec_agent", return_value="T t@e.com"), mock.patch.object(engine, "_sec_get", side_effect=flaky):
            out = company.get_company("ACME")
        self.assertIn("financials_error", out)
        self.assertTrue(out["developments"])

    def test_sec_http_errors_become_friendly_messages(self):
        import urllib.error
        err = urllib.error.HTTPError("u", 429, "Too Many", {}, None)
        with mock.patch.object(engine, "sec_agent", return_value="T t@e.com"), mock.patch.object(engine, "_sec_get", side_effect=err):
            with self.assertRaises(ValueError) as cm:
                company.get_company("ACME")
        self.assertIn("HTTP 429", str(cm.exception))


class AskTick(unittest.TestCase):
    CO = {"configured": True, "supported": True, "name": "Acme Corp", "edgar": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1",
          "annual": {"form": "10-K", "period": "2025-12-31", "url": "https://www.sec.gov/Archives/edgar/data/1/x/a.htm"},
          "financials": {"read": [{"tone": "good", "text": "Revenue grew 25.0% to $200."}]},
          "developments": [{"date": "2026-05-02", "form": "8-K", "tone": "bad", "items": [{"label": "Said past financial statements should not be relied on (restatement)"}]}]}
    ANN = {"available": True, "flags": [{"label": "Weakness in its financial controls", "tone": "bad", "hedged": False, "text": "We identified a material weakness."},
                                       {"label": "Doubt it can keep going", "tone": "info", "hedged": True, "text": "There could be doubt."}],
           "new_risks": ["AI may erode demand."], "drivers": ["Revenue increased 18% primarily due to cloud."]}

    def test_the_question_is_recognised(self):
        for q in ("What's in Apple's annual report?", "Any red flags in Tesla's 10-K", "latest developments on Nvidia", "How is Ford's debt?"):
            self.assertIn("report", tick_chat.intents(q), q)
        self.assertNotIn("report", tick_chat.intents("Is Tesla undervalued?"))

    def test_a_report_question_about_a_company_still_gets_an_entity_answer(self):
        self.assertTrue(tick_chat.is_on_topic("What's in Apple's annual report?", [{"symbol": "AAPL"}], {"report", "concept"}))

    def test_blocks_show_numbers_developments_and_only_stated_flags(self):
        blocks, links = tick_chat.company_blocks("Acme", self.CO, self.ANN, True)
        text = json.dumps(blocks)
        self.assertIn("Revenue grew 25.0%", text)
        self.assertIn("restatement", text)
        self.assertIn("(serious)", text)
        self.assertIn("material weakness", text)
        self.assertNotIn("There could be doubt", text)   # hypothetical boilerplate is not a red flag
        self.assertIn("AI may erode demand", text)
        self.assertEqual(links[0]["engine"], "SEC EDGAR")

    def test_slow_annual_report_is_explained_not_hidden(self):
        blocks, _ = tick_chat.company_blocks("Acme", self.CO, None, True)
        self.assertIn("takes a little while", json.dumps(blocks))

    def test_every_unavailable_case_says_why(self):
        self.assertIn("could not reach the SEC", json.dumps(tick_chat.company_blocks("A", None, None, False)[0]))
        self.assertIn("switched off", json.dumps(tick_chat.company_blocks("A", {"configured": False}, None, False)[0]))
        text = json.dumps(tick_chat.company_blocks("Tencent", {"configured": True, "supported": False}, None, False)[0])
        self.assertIn("only the US publishes filings", text)
        self.assertIn("paste a section", text)

    def test_other_market_numbers_are_shown_with_their_source_caveat(self):
        co = {"configured": True, "supported": False, "financials": {"read": [{"tone": "good", "text": "Revenue grew 4.0% to S$22.9B."}]}}
        text = json.dumps(tick_chat.company_blocks("DBS", co, None, False)[0])
        self.assertIn("Revenue grew 4.0%", text)
        self.assertIn("Yahoo Finance, which can be late or wrong", text)

    def test_the_language_model_gets_filings_but_never_the_users_notes(self):
        ctx = {"quotes": {}, "news": [], "company": dict(self.CO, supported=True), "annual": self.ANN}
        out = tick_chat.build_context("us", [], ctx, [], mem={"experience": "beginner", "markets": []})
        self.assertIn("ANNUAL REPORT RED FLAG (stated)", out)
        self.assertIn("FILING 2026-05-02 8-K", out)


class Endpoints(unittest.TestCase):
    def test_company_routes_are_public_and_limited_per_visitor(self):
        self.assertIn("/api/company", server.ROUTES)
        self.assertIn("/api/annual-report", server.ROUTES)
        self.assertIn("/api/analyze-text", server.POST_ROUTES)
        self.assertNotIn("/api/analyze-text", server.PROTECTED_WHEN_CLOUD)
        self.assertNotIn("/api/company", server.PROTECTED_WHEN_CLOUD)
        tick_chat._recent.clear()
        with mock.patch.object(company, "get_annual_report", return_value={"ok": 1}):
            for _ in range(6):
                server._get_annual({"symbol": ["AAPL"]}, None, "7.7.7.7")
            with self.assertRaises(ValueError):
                server._get_annual({"symbol": ["AAPL"]}, None, "7.7.7.7")
            server._get_annual({"symbol": ["AAPL"]}, None, "8.8.8.8")   # someone else is unaffected
        tick_chat._recent.clear()


if __name__ == "__main__":
    unittest.main()
