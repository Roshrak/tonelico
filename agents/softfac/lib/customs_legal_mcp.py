#!/usr/bin/env python3
"""MCP server for Customs Clearance, Import/Export Operations, Tariff/Duty Calculation, and Legal Processing."""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List


def _ok(data: Any) -> dict:
    text = json.dumps(data, ensure_ascii=False, indent=2) if not isinstance(data, str) else data
    return {"content": [{"type": "text", "text": text}]}


def _err(msg: str) -> dict:
    return {"isError": True, "content": [{"type": "text", "text": msg}]}


HS_DATABASE = [
    {
        "hs_code": "1207.40.90",
        "description_vi": "Hạt vừng (hạt mè), đã hoặc chưa vỡ mảnh - Loại khác (Sesamum seeds, roasted/hulled)",
        "description_en": "Sesamum seeds, whether or not broken - Other (including roasted white sesame seeds)",
        "mfn_rate": 10.0,
        "atiga_form_d": 0.0,
        "acfta_form_e": 0.0,
        "evfta_eur1": 0.0,
        "cptpp": 0.0,
        "akfta_form_ak": 0.0,
        "vat_rate": 8.0,
        "specialized_inspection": [
            "Kiểm dịch thực vật (Plant Quarantine - Thông tư 33/2014/TT-BNNPTNT)",
            "Kiểm tra nhà nước về ATTP (State Food Safety Inspection - Nghị định 15/2018/NĐ-CP - Bộ NN&PTNT)",
        ],
    },
    {
        "hs_code": "0801.32.00",
        "description_vi": "Hạt điều đã bóc vỏ (Cashew nuts, shelled)",
        "description_en": "Cashew nuts, shelled",
        "mfn_rate": 25.0,
        "atiga_form_d": 0.0,
        "acfta_form_e": 0.0,
        "evfta_eur1": 0.0,
        "cptpp": 0.0,
        "akfta_form_ak": 0.0,
        "vat_rate": 8.0,
        "specialized_inspection": [
            "Kiểm dịch thực vật (Plant Quarantine)",
            "Kiểm tra nhà nước về ATTP (Nghị định 15/2018/NĐ-CP)",
        ],
    },
    {
        "hs_code": "0901.21.10",
        "description_vi": "Cà phê đã rang, chưa khử chất cafein, chưa xay",
        "description_en": "Coffee, roasted, not decaffeinated, unground",
        "mfn_rate": 40.0,
        "atiga_form_d": 0.0,
        "acfta_form_e": 5.0,
        "evfta_eur1": 0.0,
        "cptpp": 0.0,
        "akfta_form_ak": 0.0,
        "vat_rate": 8.0,
        "specialized_inspection": ["Kiểm tra nhà nước về ATTP (Bộ Công Thương / Bộ NN&PTNT - Nghị định 15/2018/NĐ-CP)"],
    },
    {
        "hs_code": "1905.31.10",
        "description_vi": "Bánh quy ngọt (Sweet biscuits), không chứa ca cao",
        "description_en": "Sweet biscuits, not containing cocoa",
        "mfn_rate": 35.0,
        "atiga_form_d": 0.0,
        "acfta_form_e": 0.0,
        "evfta_eur1": 0.0,
        "cptpp": 0.0,
        "akfta_form_ak": 0.0,
        "vat_rate": 8.0,
        "specialized_inspection": ["Tự công bố sản phẩm & Kiểm tra ATTP nhập khẩu (Bộ Công Thương - Nghị định 15/2018/NĐ-CP)"],
    },
    {
        "hs_code": "2106.90.99",
        "description_vi": "Thực phẩm bảo vệ sức khỏe / Chế phẩm thực phẩm khác",
        "description_en": "Health supplements / Other food preparations not elsewhere specified",
        "mfn_rate": 15.0,
        "atiga_form_d": 0.0,
        "acfta_form_e": 0.0,
        "evfta_eur1": 0.0,
        "cptpp": 0.0,
        "akfta_form_ak": 0.0,
        "vat_rate": 8.0,
        "specialized_inspection": ["Đăng ký bản công bố sản phẩm (Cục ATTP - Bộ Y tế - Điều 6 Nghị định 15/2018/NĐ-CP)"],
    },
    {
        "hs_code": "8471.30.20",
        "description_vi": "Máy tính xách tay (Laptops, notebooks, subnotebooks)",
        "description_en": "Portable automatic data processing machines (laptops)",
        "mfn_rate": 0.0,
        "atiga_form_d": 0.0,
        "acfta_form_e": 0.0,
        "evfta_eur1": 0.0,
        "cptpp": 0.0,
        "akfta_form_ak": 0.0,
        "vat_rate": 10.0,
        "specialized_inspection": [
            "Kiểm tra chất lượng & Hợp quy thu phát sóng (Bộ TT&TT - Thông tư 02/2024/TT-BTTTT)",
            "Hiệu suất năng lượng tối thiểu (MOIT)",
        ],
    },
    {
        "hs_code": "8473.30.80",
        "description_vi": "Bộ phận và phụ kiện của máy xử lý dữ liệu (Card đồ họa GPU, bo mạch)",
        "description_en": "Parts and accessories of data processing machines (Graphics cards / GPUs, motherboards)",
        "mfn_rate": 0.0,
        "atiga_form_d": 0.0,
        "acfta_form_e": 0.0,
        "evfta_eur1": 0.0,
        "cptpp": 0.0,
        "akfta_form_ak": 0.0,
        "vat_rate": 10.0,
        "specialized_inspection": ["Không thuộc diện cấm nhập khẩu (hàng mới 100%); hàng cũ thuộc danh mục cấm NK theo Thông tư 11/2018/TT-BTTTT"],
    },
]

INCOTERMS_2020 = {
    "EXW": {"name": "Ex Works", "mode": "Any", "seller_pays_freight": False, "seller_pays_insurance": False, "seller_clears_export": False, "seller_clears_import": False, "risk_transfer": "At seller's premises"},
    "FCA": {"name": "Free Carrier", "mode": "Any", "seller_pays_freight": False, "seller_pays_insurance": False, "seller_clears_export": True, "seller_clears_import": False, "risk_transfer": "On buyer's nominated carrier at named place"},
    "FAS": {"name": "Free Alongside Ship", "mode": "Sea/Inland Waterway", "seller_pays_freight": False, "seller_pays_insurance": False, "seller_clears_export": True, "seller_clears_import": False, "risk_transfer": "Alongside vessel at port of loading"},
    "FOB": {"name": "Free On Board", "mode": "Sea/Inland Waterway", "seller_pays_freight": False, "seller_pays_insurance": False, "seller_clears_export": True, "seller_clears_import": False, "risk_transfer": "On board vessel at port of loading"},
    "CFR": {"name": "Cost and Freight", "mode": "Sea/Inland Waterway", "seller_pays_freight": True, "seller_pays_insurance": False, "seller_clears_export": True, "seller_clears_import": False, "risk_transfer": "On board vessel at port of loading (cost paid to destination port)"},
    "CIF": {"name": "Cost, Insurance and Freight", "mode": "Sea/Inland Waterway", "seller_pays_freight": True, "seller_pays_insurance": True, "seller_clears_export": True, "seller_clears_import": False, "risk_transfer": "On board vessel at port of loading (Institute Cargo Clauses C minimum)"},
    "CPT": {"name": "Carriage Paid To", "mode": "Any", "seller_pays_freight": True, "seller_pays_insurance": False, "seller_clears_export": True, "seller_clears_import": False, "risk_transfer": "Handed over to first carrier"},
    "CIP": {"name": "Carriage and Insurance Paid To", "mode": "Any", "seller_pays_freight": True, "seller_pays_insurance": True, "seller_clears_export": True, "seller_clears_import": False, "risk_transfer": "Handed over to first carrier (Institute Cargo Clauses A all-risks)"},
    "DAP": {"name": "Delivered at Place", "mode": "Any", "seller_pays_freight": True, "seller_pays_insurance": False, "seller_clears_export": True, "seller_clears_import": False, "risk_transfer": "At named destination ready for unloading"},
    "DPU": {"name": "Delivered at Place Unloaded", "mode": "Any", "seller_pays_freight": True, "seller_pays_insurance": False, "seller_clears_export": True, "seller_clears_import": False, "risk_transfer": "At named destination after unloading"},
    "DDP": {"name": "Delivered Duty Paid", "mode": "Any", "seller_pays_freight": True, "seller_pays_insurance": False, "seller_clears_export": True, "seller_clears_import": True, "risk_transfer": "At named destination cleared for import with all duties paid"},
}


class CustomsLegalMcpServer:
    def list_tools(self) -> list[dict]:
        return [
            {
                "name": "customs_hs_code_lookup",
                "description": "Search Vietnam Import/Export Tariff HS codes and return MFN, ATIGA (Form D), ACFTA (Form E), EVFTA (EUR.1), CPTPP, AKFTA tariff rates, VAT, and Specialized Inspection requirements.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "HS code prefix (e.g. 1207, 8471) or commodity keyword (e.g. mè, sesame, cashew, laptop, gpu)"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "customs_calculate_import_duty",
                "description": "Calculate Vietnam Customs CIF taxable value, Import Duty, Special Consumption Tax (SCT), Environmental Tax, and Import VAT in VND and foreign currency.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "fob_or_invoice_value": {"type": "number", "description": "Invoice/FOB value in foreign currency"},
                        "freight_cost": {"type": "number", "description": "International freight cost (0 if already CIF)"},
                        "insurance_cost": {"type": "number", "description": "Insurance premium (0 if uninsured or CIF)"},
                        "exchange_rate_vnd": {"type": "number", "description": "Customs exchange rate (e.g. 25450 VND/USD)"},
                        "import_duty_rate_pct": {"type": "number", "description": "Import duty rate % (e.g. 0, 5, 10, 25)"},
                        "sct_rate_pct": {"type": "number", "description": "Special Consumption Tax % (default 0)"},
                        "vat_rate_pct": {"type": "number", "description": "Import VAT rate % (default 8 or 10)"},
                    },
                    "required": ["fob_or_invoice_value", "exchange_rate_vnd", "import_duty_rate_pct"],
                },
            },
            {
                "name": "customs_incoterms_calculator",
                "description": "Analyze Incoterms 2020 responsibilities and convert shipment pricing across EXW, FOB, CFR, CIF, DAP, and DDP.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "incoterm": {"type": "string", "description": "Incoterm 2020 code (EXW, FCA, FOB, CFR, CIF, CPT, CIP, DAP, DPU, DDP)"},
                        "exw_value": {"type": "number", "description": "Optional base EXW/FOB goods value"},
                        "origin_local_charges": {"type": "number", "description": "Origin trucking, THC, export customs"},
                        "main_freight": {"type": "number", "description": "Ocean/Air main freight"},
                        "insurance": {"type": "number", "description": "Cargo insurance"},
                        "dest_charges_and_duty": {"type": "number", "description": "Destination THC, D/O, import duty & delivery"},
                    },
                    "required": ["incoterm"],
                },
            },
            {
                "name": "customs_validate_co_form",
                "description": "Validate Certificate of Origin (C/O Form D, E, AK, AJ, VJ, EUR.1, CPTPP, VK) compliance rules, origin criteria (WO, PE, RVC40, CTC), third-party invoicing, and validity.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "form_type": {"type": "string", "description": "Form D, Form E, Form AK, EUR.1, CPTPP, Form VJ, etc."},
                        "origin_criterion": {"type": "string", "description": "Origin criterion in Box 8 (e.g. WO, PE, RVC 40%, CTH, CTSH)"},
                        "issue_date": {"type": "string", "description": "C/O issue date (YYYY-MM-DD)"},
                        "shipment_date": {"type": "string", "description": "B/L shipment/on-board date (YYYY-MM-DD)"},
                        "third_party_invoice": {"type": "boolean", "description": "Whether invoice is issued by a third-country entity"},
                        "retroactive_ticked": {"type": "boolean", "description": "Whether 'Issued Retroactively' box is ticked"},
                    },
                    "required": ["form_type", "origin_criterion"],
                },
            },
            {
                "name": "customs_cross_check_shipping_docs",
                "description": "Cross-check Commercial Invoice, Packing List, Bill of Lading (B/L), and C/O data for customs discrepancies.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "invoice": {"type": "object", "description": "Invoice fields: consignee, total_value, currency, incoterm, quantity, description"},
                        "packing_list": {"type": "object", "description": "Packing list fields: net_weight_kg, gross_weight_kg, packages, quantity"},
                        "bill_of_lading": {"type": "object", "description": "B/L fields: consignee, gross_weight_kg, packages, hs_code, freight_terms"},
                        "co_form": {"type": "object", "description": "Optional C/O fields: consignee, weight_or_qty, hs_code_6digit, invoice_no"},
                    },
                    "required": ["invoice", "packing_list", "bill_of_lading"],
                },
            },
            {
                "name": "customs_vnaccs_declaration_check",
                "description": "Audit Vietnam Customs VNACCS/VCIS declaration type code (Mã loại hình A11, A12, A41, E11, E21, E31, B11, G11), lane risk (Green/Yellow/Red), and required e-dossier attachments.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "declaration_type": {"type": "string", "description": "VNACCS code: A11, A12, E11, E21, E31, B11, G11, H11, etc."},
                        "has_preferential_co": {"type": "boolean", "description": "Whether claiming FTA tariff preference via C/O"},
                        "requires_specialized_inspection": {"type": "boolean", "description": "Whether goods require quarantine or quality inspection"},
                    },
                    "required": ["declaration_type"],
                },
            },
            {
                "name": "customs_food_safety_decree15",
                "description": "Determine Vietnam Decree 15/2018/NĐ-CP food safety procedure (Self-Declaration vs Registration), managing Ministry (MOH/MARD/MOIT), and State Inspection method (Reduced/Normal/Tight).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "product_name": {"type": "string", "description": "Food product name (e.g. Hạt mè trắng rang, Thực phẩm bảo vệ sức khỏe)"},
                        "product_group": {"type": "string", "description": "conventional_food, health_supplement, medical_nutrition, infant_formula_under_36m, food_additive"},
                        "consecutive_passed_shipments": {"type": "integer", "description": "Number of consecutive shipments that passed Normal Inspection with C/O"},
                    },
                    "required": ["product_name", "product_group"],
                },
            },
            {
                "name": "customs_specialized_inspection_lookup",
                "description": "Check Specialized Inspection (Kiểm tra chuyên ngành) regulations, Ministries, and legal circulars for any commodity group.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "commodity_type": {"type": "string", "description": "plant_products, animal_products, food_beverage, electronics_it, machinery_used, chemicals, cosmetics_medical"},
                    },
                    "required": ["commodity_type"],
                },
            },
            {
                "name": "customs_generate_self_declaration",
                "description": "Generate a complete Vietnam Food Safety Self-Declaration (Bản tự công bố sản phẩm - Mẫu số 01 Nghị định 15/2018/NĐ-CP) from company & lab test certificate data.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "company_name": {"type": "string", "description": "Enterprise name (e.g. CÔNG TY CỔ PHẦN THƯƠNG MẠI DỊCH VỤ BÁCH GIA FOOD)"},
                        "address": {"type": "string", "description": "Registered address"},
                        "product_name": {"type": "string", "description": "Product name (e.g. Hạt mè trắng rang)"},
                        "lab_name": {"type": "string", "description": "ISO 17025 accredited lab (e.g. TRUNG TÂM PHÂN TÍCH VÀ THỬ NGHIỆM 2 - VINACONTROL)"},
                        "certificate_no": {"type": "string", "description": "Lab test certificate code (e.g. 26G15TND20171)"},
                        "packaging_spec": {"type": "string", "description": "Packaging material and net weight"},
                        "output_path": {"type": "string", "description": "Optional path to save the generated declaration text"},
                    },
                    "required": ["company_name", "product_name"],
                },
            },
            {
                "name": "customs_parse_bill_of_lading",
                "description": "Parse raw Bill of Lading (B/L) or Air Waybill text into structured customs fields.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "bl_text": {"type": "string", "description": "Raw text of Bill of Lading"},
                    },
                    "required": ["bl_text"],
                },
            },
            {
                "name": "customs_parse_commercial_invoice",
                "description": "Parse raw Commercial Invoice text into structured header fields, payment terms, Incoterms, and amounts.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "invoice_text": {"type": "string", "description": "Raw text of Commercial Invoice"},
                    },
                    "required": ["invoice_text"],
                },
            },
            {
                "name": "customs_parse_packing_list",
                "description": "Parse raw Packing List text to extract Net Weight, Gross Weight, CBM, and package counts.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "packing_list_text": {"type": "string", "description": "Raw text of Packing List"},
                    },
                    "required": ["packing_list_text"],
                },
            },
            {
                "name": "legal_contract_clause_audit",
                "description": "Audit commercial or international sales contract text for essential legal clauses under Vietnam Commercial Law 2005, Civil Code 2015, and CISG.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "contract_text": {"type": "string", "description": "Contract text or file path"},
                    },
                    "required": ["contract_text"],
                },
            },
            {
                "name": "legal_diploma_recognition_check",
                "description": "Verify foreign degree recognition dossier requirements for Cục Quản lý Chất lượng - Bộ GD&ĐT (NARIC Vietnam, Thông tư 13/2021/TT-BGDĐT).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "holder_name": {"type": "string"},
                        "issuing_institution": {"type": "string"},
                        "country": {"type": "string"},
                        "program_type": {"type": "string", "description": "full_abroad, joint_program, online_blended"},
                        "certificate_text": {"type": "string", "description": "Optional OCR text from recognition certificate"},
                    },
                    "required": ["issuing_institution", "country"],
                },
            },
            {
                "name": "legal_check_vietnam_mst",
                "description": "Validate Vietnamese Enterprise Tax Code (Mã số thuế 10 or 13 digits) format and structure.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "mst": {"type": "string", "description": "Tax code string"},
                    },
                    "required": ["mst"],
                },
            },
            {
                "name": "customs_container_load_planner",
                "description": "Calculate container utilization (20GP, 40GP, 40HQ) by CBM volume and payload weight for a shipment.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "total_cbm": {"type": "number", "description": "Total cargo volume in CBM"},
                        "total_gross_weight_kg": {"type": "number", "description": "Total cargo gross weight in kg"},
                    },
                    "required": ["total_cbm", "total_gross_weight_kg"],
                },
            },
            {
                "name": "customs_demurrage_detention_calc",
                "description": "Calculate free-time expiration and Demurrage & Detention (DEM/DET) container charges.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "total_days_used": {"type": "integer", "description": "Total days from discharge to empty return"},
                        "free_days": {"type": "integer", "description": "Granted free DEM+DET days (e.g. 7, 14, 21)"},
                        "container_count": {"type": "integer", "description": "Number of containers"},
                        "daily_rate_usd": {"type": "number", "description": "Overdue rate in USD/day per container (default 35)"},
                    },
                    "required": ["total_days_used", "free_days"],
                },
            },
            {
                "name": "customs_dossier_checklist",
                "description": "Generate a complete legal & customs clearance document checklist for any import/export shipment mode.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "direction": {"type": "string", "description": "import or export"},
                        "mode": {"type": "string", "description": "sea_fcl, sea_lcl, air, express, bonded"},
                        "commodity": {"type": "string", "description": "food, agricultural, electronics, machinery, general"},
                    },
                    "required": ["direction", "mode"],
                },
            },
        ]

    def call_tool(self, name: str, args: Dict[str, Any]) -> dict:
        try:
            if name == "customs_hs_code_lookup":
                q = args["query"].strip().lower()
                matches = [
                    item for item in HS_DATABASE
                    if q in item["hs_code"].lower()
                    or q in item["description_vi"].lower()
                    or q in item["description_en"].lower()
                ]
                return _ok({
                    "query": args["query"],
                    "match_count": len(matches),
                    "matches": matches if matches else HS_DATABASE,
                    "classification_rules": "GRI 1-6 (General Rules for the Interpretation of the Harmonized System - Thông tư 31/2022/TT-BTC)",
                })

            elif name == "customs_calculate_import_duty":
                fob = float(args["fob_or_invoice_value"])
                freight = float(args.get("freight_cost", 0.0))
                ins = float(args.get("insurance_cost", 0.0))
                fx = float(args["exchange_rate_vnd"])
                duty_pct = float(args["import_duty_rate_pct"])
                sct_pct = float(args.get("sct_rate_pct", 0.0))
                vat_pct = float(args.get("vat_rate_pct", 8.0))

                cif_fc = fob + freight + ins
                cif_vnd = round(cif_fc * fx)
                import_duty_vnd = round(cif_vnd * (duty_pct / 100.0))
                sct_vnd = round((cif_vnd + import_duty_vnd) * (sct_pct / 100.0))
                vat_vnd = round((cif_vnd + import_duty_vnd + sct_vnd) * (vat_pct / 100.0))
                total_tax_vnd = import_duty_vnd + sct_vnd + vat_vnd
                return _ok({
                    "cif_foreign_currency": round(cif_fc, 2),
                    "exchange_rate_vnd": fx,
                    "customs_value_cif_vnd": cif_vnd,
                    "import_duty_rate_pct": duty_pct,
                    "import_duty_vnd": import_duty_vnd,
                    "sct_rate_pct": sct_pct,
                    "sct_vnd": sct_vnd,
                    "vat_rate_pct": vat_pct,
                    "import_vat_vnd": vat_vnd,
                    "total_customs_taxes_vnd": total_tax_vnd,
                    "total_landed_cost_vnd": cif_vnd + total_tax_vnd,
                })

            elif name == "customs_incoterms_calculator":
                code = args["incoterm"].strip().upper()
                rule = INCOTERMS_2020.get(code)
                if not rule:
                    return _err(f"Unknown Incoterm 2020: {code}. Valid: {list(INCOTERMS_2020.keys())}")
                exw = float(args.get("exw_value", 0.0))
                orig = float(args.get("origin_local_charges", 0.0))
                frt = float(args.get("main_freight", 0.0))
                ins = float(args.get("insurance", 0.0))
                dest = float(args.get("dest_charges_and_duty", 0.0))
                breakdown = {
                    "EXW": exw,
                    "FOB_FCA": exw + orig,
                    "CFR_CPT": exw + orig + frt,
                    "CIF_CIP": exw + orig + frt + ins,
                    "DDP": exw + orig + frt + ins + dest,
                }
                return _ok({"incoterm": code, "rule_details": rule, "price_ladder": breakdown})

            elif name == "customs_validate_co_form":
                form = args["form_type"].strip().upper()
                crit = args["origin_criterion"].strip().upper()
                issues = []
                issue_dt = args.get("issue_date", "")
                ship_dt = args.get("shipment_date", "")
                if issue_dt and ship_dt and issue_dt > ship_dt:
                    days_diff = 4
                    if not args.get("retroactive_ticked", False):
                        issues.append("C/O issued after shipment date: verify whether 'ISSUED RETROACTIVELY' is required (normally >3 days after B/L date).")
                if args.get("third_party_invoice") and form in ("FORM D", "FORM E", "FORM AK"):
                    issues.append("Third-Party Invoicing used: Box 13 'Third Party Invoicing' MUST be ticked and third-party company name/country listed in Box 7.")
                return _ok({
                    "form_type": form,
                    "origin_criterion": crit,
                    "valid": len(issues) == 0,
                    "warnings_and_requirements": issues,
                    "validity_period": "12 months from date of issuance (24 months for EUR.1/EVFTA self-certification)",
                })

            elif name == "customs_cross_check_shipping_docs":
                inv = args.get("invoice") or {}
                pl = args.get("packing_list") or {}
                bl = args.get("bill_of_lading") or {}
                co = args.get("co_form") or {}
                mismatches = []
                if pl.get("gross_weight_kg") and bl.get("gross_weight_kg"):
                    if abs(float(pl["gross_weight_kg"]) - float(bl["gross_weight_kg"])) > 0.01:
                        mismatches.append(f"Gross weight mismatch: Packing List ({pl['gross_weight_kg']}) != B/L ({bl['gross_weight_kg']})")
                if pl.get("net_weight_kg") and pl.get("gross_weight_kg"):
                    if float(pl["net_weight_kg"]) > float(pl["gross_weight_kg"]):
                        mismatches.append("Net weight exceeds Gross weight on Packing List")
                if pl.get("packages") and bl.get("packages") and pl["packages"] != bl["packages"]:
                    mismatches.append(f"Package count mismatch: Packing List ({pl['packages']}) != B/L ({bl['packages']})")
                if inv.get("consignee") and bl.get("consignee"):
                    if inv["consignee"].strip().lower() != bl["consignee"].strip().lower() and "to order" not in bl["consignee"].lower():
                        mismatches.append("Consignee mismatch between Invoice and B/L")
                if co.get("hs_code_6digit") and bl.get("hs_code"):
                    if not str(bl["hs_code"]).replace(".", "").startswith(str(co["hs_code_6digit"]).replace(".", "")[:6]):
                        mismatches.append("6-digit HS heading mismatch between C/O and B/L/Declaration (requires circular verification)")
                return _ok({
                    "status": "PASS" if not mismatches else "DISCREPANCY_FOUND",
                    "discrepancy_count": len(mismatches),
                    "discrepancies": mismatches,
                })

            elif name == "customs_vnaccs_declaration_check":
                dtype = args["declaration_type"].strip().upper()
                types_map = {
                    "A11": "Nhập kinh doanh tiêu dùng (Commercial Import for Consumption)",
                    "A12": "Nhập kinh doanh sản xuất (Import for Domestic Production)",
                    "A41": "Nhập kinh doanh của doanh nghiệp đầu tư (FDI Import)",
                    "E11": "Nhập nguyên liệu của DNCX từ nước ngoài (EPE Import)",
                    "E21": "Nhập nguyên liệu để gia công cho thương nhân nước ngoài (Processing Import)",
                    "E31": "Nhập nguyên liệu sản xuất xuất khẩu (SXXK Import)",
                    "B11": "Xuất kinh doanh (Commercial Export)",
                    "G11": "Tạm nhập hàng kinh doanh tạm nhập tái xuất (Temporary Import for Re-export)",
                    "H11": "Hàng nhập khẩu khác (Quà biếu, tặng, hàng mẫu không thanh toán)",
                }
                has_co = bool(args.get("has_preferential_co", False))
                has_spec = bool(args.get("requires_specialized_inspection", False))
                lane = "Yellow (Luồng Vàng - Document Check)" if (has_co or has_spec) else "Green (Luồng Xanh - Auto Clearance)"
                docs = ["Commercial Invoice", "Bill of Lading (B/L)", "Customs Value Declaration (if applicable)"]
                if has_co:
                    docs.append("Certificate of Origin (C/O) or REX/CPTPP Self-Certification")
                if has_spec:
                    docs.append("Specialized Inspection Registration / Result Certificate (Giấy đăng ký/Kết quả KTNN trên VNSW)")
                return _ok({
                    "declaration_type": dtype,
                    "description": types_map.get(dtype, "Custom VNACCS Declaration Code"),
                    "predicted_channel": lane,
                    "mandatory_e_dossier_v5": docs,
                })

            elif name == "customs_food_safety_decree15":
                pgroup = args["product_group"].strip().lower()
                passed = int(args.get("consecutive_passed_shipments", 0))
                if pgroup in ("health_supplement", "medical_nutrition", "infant_formula_under_36m"):
                    proc = "Đăng ký bản công bố sản phẩm (Registration of Product Declaration - Article 6 Decree 15/2018/NĐ-CP)"
                    ministry = "Bộ Y tế (Ministry of Health - Cục An toàn thực phẩm)"
                else:
                    proc = "Tự công bố sản phẩm (Self-Declaration - Article 4 & 5 Decree 15/2018/NĐ-CP)"
                    ministry = "Bộ NN&PTNT (Agricultural/Seeds/Grains) or Bộ Công Thương (Processed Food/Beverages) or Ban Quản lý ATTP"
                insp_mode = "Kiểm tra giảm (Reduced Inspection - 5% dossier random check)" if passed >= 3 else "Kiểm tra thông thường (Normal Inspection - Dossier review)"
                return _ok({
                    "product_name": args["product_name"],
                    "procedure": proc,
                    "managing_authority": ministry,
                    "state_import_inspection_mode": insp_mode,
                    "required_documents": [
                        "Bản tự công bố sản phẩm (Mẫu số 01 Nghị định 15/2018/NĐ-CP)",
                        "Phiếu kết quả kiểm nghiệm an toàn thực phẩm trong vòng 12 tháng tại phòng Lab đạt chuẩn ISO 17025 (Vinacontrol / Quatest)",
                        "Nhãn sản phẩm / Nhãn phụ tiếng Việt",
                    ],
                })

            elif name == "customs_specialized_inspection_lookup":
                ctype = args["commodity_type"].strip().lower()
                rules = {
                    "plant_products": {
                        "agency": "Cục Bảo vệ thực vật - Bộ NN&PTNT",
                        "procedure": "Kiểm dịch thực vật nhập khẩu / xuất khẩu (Phytosanitary Certificate)",
                        "portal": "https://vnsw.gov.vn (Cổng thông tin một cửa quốc gia)",
                    },
                    "food_beverage": {
                        "agency": "Bộ Y tế / Bộ NN&PTNT / Bộ Công Thương",
                        "procedure": "Kiểm tra nhà nước về an toàn thực phẩm nhập khẩu (Nghị định 15/2018/NĐ-CP)",
                        "portal": "https://vnsw.gov.vn",
                    },
                    "electronics_it": {
                        "agency": "Bộ Thông tin và Truyền thông / Bộ Khoa học và Công nghệ",
                        "procedure": "Kiểm tra chất lượng hàng nhập khẩu, Chứng nhận hợp quy (CR), Hiệu suất năng lượng",
                        "portal": "https://vnsw.gov.vn",
                    },
                }
                return _ok(rules.get(ctype, {"agency": "Relevant Line Ministry", "portal": "https://vnsw.gov.vn"}))

            elif name == "customs_generate_self_declaration":
                comp = args["company_name"]
                addr = args.get("address", "TP. Hồ Chí Minh, Việt Nam")
                prod = args["product_name"]
                lab = args.get("lab_name", "TRUNG TÂM PHÂN TÍCH VÀ THỬ NGHIỆM 2 - VINACONTROL")
                cert = args.get("certificate_no", "26G15TND20171")
                pack = args.get("packaging_spec", "Túi nhựa PE/PA chuyên dùng cho thực phẩm")
                doc_text = f"""CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM
Độc lập - Tự do - Hạnh phúc
----------------
BẢN TỰ CÔNG BỐ SẢN PHẨM
(Ban hành kèm theo Nghị định số 15/2018/NĐ-CP ngày 02 tháng 02 năm 2018 của Chính phủ)

I. Thông tin về tổ chức, cá nhân tự công bố sản phẩm
- Tên tổ chức, cá nhân: {comp}
- Địa chỉ: {addr}

II. Thông tin về sản phẩm
1. Tên sản phẩm: {prod}
2. Thành phần: 100% {prod}
3. Quy cách đóng gói và chất liệu bao bì: {pack}

III. Mẫu nhãn sản phẩm (đính kèm)

IV. Yêu cầu về an toàn thực phẩm
Tổ chức, cá nhân sản xuất, kinh doanh thực phẩm đạt yêu cầu về an toàn thực phẩm theo:
- QCVN 8-1:2011/BYT: Quy chuẩn kỹ thuật quốc gia đối với giới hạn ô nhiễm độc tố vi nấm trong thực phẩm (Aflatoxin B1, Aflatoxin tổng số, Ochratoxin A).
- QCVN 8-2:2011/BYT: Quy chuẩn kỹ thuật quốc gia đối với giới hạn ô nhiễm kim loại nặng trong thực phẩm (Pb, Cd, As, Hg).
- Phiếu kết quả thử nghiệm số: {cert} do {lab} cấp.

Chúng tôi xin cam kết thực hiện đầy đủ các quy định của pháp luật về an toàn thực phẩm và hoàn toàn chịu trách nhiệm về tính pháp lý của hồ sơ công bố và chất lượng, an toàn thực phẩm đối với sản phẩm đã công bố./.
"""
                if args.get("output_path"):
                    out = Path(args["output_path"]).expanduser().resolve()
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(doc_text, encoding="utf-8")
                    return _ok({"saved_to": str(out), "declaration_text": doc_text})
                return _ok({"declaration_text": doc_text})

            elif name == "customs_parse_bill_of_lading":
                txt = args["bl_text"]
                bl_no = re.search(r"(?:B/L\s*No\.?|Bill of Lading\s*No\.?)\s*[:#]?\s*([A-Z0-9\-]+)", txt, re.I)
                cntr = re.findall(r"\b[A-Z]{4}\d{7}\b", txt)
                gw = re.search(r"(\d[\d,\.]*)\s*(?:KGS|KG)\b", txt, re.I)
                cbm = re.search(r"(\d[\d,\.]*)\s*(?:CBM|M3)\b", txt, re.I)
                freight = "FREIGHT PREPAID" if "prepaid" in txt.lower() else ("FREIGHT COLLECT" if "collect" in txt.lower() else "UNKNOWN")
                return _ok({
                    "bl_number": bl_no.group(1) if bl_no else None,
                    "containers": list(dict.fromkeys(cntr)),
                    "gross_weight_kg": gw.group(1) if gw else None,
                    "measurement_cbm": cbm.group(1) if cbm else None,
                    "freight_terms": freight,
                })

            elif name == "customs_parse_commercial_invoice":
                txt = args["invoice_text"]
                inv_no = re.search(r"(?:Invoice\s*No\.?|Số hóa đơn)\s*[:#]?\s*([A-Z0-9\-/]+)", txt, re.I)
                incoterm = re.search(r"\b(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b", txt)
                curr = re.search(r"\b(USD|EUR|JPY|CNY|VND|GBP|SGD)\b", txt)
                amounts = re.findall(r"(?:TOTAL|AMOUNT)\s*[:$]?\s*(?:USD|EUR|VND)?\s*([\d,]+\.\d{2})", txt, re.I)
                return _ok({
                    "invoice_number": inv_no.group(1) if inv_no else None,
                    "incoterm": incoterm.group(1) if incoterm else None,
                    "currency": curr.group(1) if curr else None,
                    "detected_totals": amounts,
                })

            elif name == "customs_parse_packing_list":
                txt = args["packing_list_text"]
                nw = re.search(r"(?:Net\s*Weight|N\.?W\.?)\s*[:]?\s*([\d,\.]+)\s*(?:KGS|KG)?", txt, re.I)
                gw = re.search(r"(?:Gross\s*Weight|G\.?W\.?)\s*[:]?\s*([\d,\.]+)\s*(?:KGS|KG)?", txt, re.I)
                cbm = re.search(r"([\d,\.]+)\s*(?:CBM|M3)\b", txt, re.I)
                pkgs = re.search(r"(\d[\d,]*)\s*(?:CARTONS|CTNS|BAGS|PALLETS|PKGS)\b", txt, re.I)
                return _ok({
                    "net_weight_kg": nw.group(1) if nw else None,
                    "gross_weight_kg": gw.group(1) if gw else None,
                    "volume_cbm": cbm.group(1) if cbm else None,
                    "packages": pkgs.group(1) if pkgs else None,
                })

            elif name == "legal_contract_clause_audit":
                txt = args["contract_text"]
                p = Path(txt)
                if p.exists() and p.is_file():
                    txt = p.read_text(encoding="utf-8", errors="replace")
                lower = txt.lower()
                checks = {
                    "incoterms_and_delivery": any(w in lower for w in ("incoterms", "fob", "cif", "giao hàng", "shipment")),
                    "payment_terms": any(w in lower for w in ("payment", "thanh toán", "l/c", "t/t", "letter of credit")),
                    "quality_and_inspection": any(w in lower for w in ("quality", "inspection", "vinacontrol", "sgs", "quatest", "chất lượng")),
                    "force_majeure": any(w in lower for w in ("force majeure", "bất khả kháng")),
                    "dispute_resolution_arbitration": any(w in lower for w in ("arbitration", "trọng tài", "viac", "court", "tòa án")),
                    "penalty_and_damages": any(w in lower for w in ("penalty", "phạt vi phạm", "liquidated damages", "bồi thường")),
                }
                missing = [k for k, v in checks.items() if not v]
                return _ok({
                    "clause_presence": checks,
                    "missing_critical_clauses": missing,
                    "legal_notes": [
                        "Under Article 301 Vietnam Commercial Law 2005, contractual penalty (phạt vi phạm) is capped at 8% of the breached obligation value.",
                        "Specify Incoterms® 2020 ICC explicitly with named port/place.",
                        "Include independent inspection agency (Vinacontrol/SGS/Quatest) at loading/discharge port as binding quality evidence.",
                    ],
                })

            elif name == "legal_diploma_recognition_check":
                return _ok({
                    "authority": "Cục Quản lý Chất lượng - Bộ Giáo dục và Đào tạo (Vietnam NARIC)",
                    "verification_portal": "https://naric.edu.vn/front/tra-cuu-van-bang",
                    "legal_basis": "Thông tư 13/2021/TT-BGDĐT quy định về điều kiện, trình tự, thủ tục, thẩm quyền công nhận văn bằng do cơ sở giáo dục nước ngoài cấp",
                    "institution": args["issuing_institution"],
                    "country": args["country"],
                    "program_type": args.get("program_type", "joint_program"),
                    "vietnam_nqf_mapping": "Bachelor (Cử nhân) = Bậc 6 Khung trình độ quốc gia Việt Nam; Master (Thạc sĩ) = Bậc 7; Doctorate (Tiến sĩ) = Bậc 8",
                })

            elif name == "legal_check_vietnam_mst":
                mst = args["mst"].strip()
                valid = bool(re.match(r"^\d{10}(-\d{3})?$", mst))
                return _ok({
                    "mst": mst,
                    "valid_format": valid,
                    "entity_type": "Branch / Dependent Unit (13-digit)" if "-" in mst else "Independent Enterprise (10-digit)",
                    "province_prefix": mst[:2] if len(mst) >= 2 else None,
                })

            elif name == "customs_container_load_planner":
                cbm = float(args["total_cbm"])
                gw = float(args["total_gross_weight_kg"])
                specs = {
                    "20GP": {"usable_cbm": 28.0, "max_payload_kg": 25000.0},
                    "40GP": {"usable_cbm": 58.0, "max_payload_kg": 26500.0},
                    "40HQ": {"usable_cbm": 68.0, "max_payload_kg": 26500.0},
                }
                rec = {}
                for ctype, sp in specs.items():
                    by_vol = math.ceil(cbm / sp["usable_cbm"])
                    by_wt = math.ceil(gw / sp["max_payload_kg"])
                    rec[ctype] = max(1, by_vol, by_wt)
                mode = "LCL (Hàng lẻ ghép cont)" if cbm < 15.0 and gw < 10000 else "FCL (Hàng nguyên cont)"
                return _ok({"total_cbm": cbm, "total_gross_weight_kg": gw, "recommended_mode": mode, "containers_needed_by_type": rec})

            elif name == "customs_demurrage_detention_calc":
                used = int(args["total_days_used"])
                free = int(args["free_days"])
                cnt = int(args.get("container_count", 1))
                rate = float(args.get("daily_rate_usd", 35.0))
                chargeable_days = max(0, used - free)
                total_usd = chargeable_days * cnt * rate
                return _ok({
                    "total_days_used": used,
                    "free_days": free,
                    "chargeable_overdue_days": chargeable_days,
                    "container_count": cnt,
                    "total_dem_det_usd": round(total_usd, 2),
                })

            elif name == "customs_dossier_checklist":
                direction = args["direction"].lower()
                mode = args["mode"].lower()
                comm = args.get("commodity", "general").lower()
                checklist = [
                    "1. Tờ khai hải quan điện tử VNACCS/VCIS (Customs Declaration)",
                    "2. Hợp đồng ngoại thương (Sales Contract - lưu doanh nghiệp / xuất trình khi tham vấn)",
                    "3. Hóa đơn thương mại (Commercial Invoice)",
                    "4. Phiếu đóng gói hàng hóa (Packing List)",
                    f"5. Vận đơn ({'Air Waybill - AWB' if 'air' in mode else 'Ocean Bill of Lading - B/L'})",
                    "6. Chứng nhận xuất xứ hàng hóa (C/O Form D/E/AK/EUR.1/CPTPP nếu hưởng ưu đãi thuế)",
                ]
                if comm in ("food", "agricultural"):
                    checklist.extend([
                        "7. Bản tự công bố sản phẩm + Phiếu kết quả kiểm nghiệm ATTP (Vinacontrol/Quatest)",
                        "8. Giấy đăng ký / Thông báo kết quả Kiểm tra nhà nước về ATTP nhập khẩu (trên VNSW)",
                        "9. Giấy chứng nhận Kiểm dịch thực vật (Phytosanitary Certificate)",
                    ])
                return _ok({"direction": direction, "mode": mode, "commodity": comm, "checklist": checklist})

            return _err(f"Unknown tool: {name}")
        except Exception as exc:
            return _err(f"Error in {name}: {exc}")

    def handle_request(self, request: dict) -> dict | None:
        method = request.get("method")
        req_id = request.get("id")
        if "id" not in request:
            return None
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "customs-legal-mcp", "version": "1.0.0"},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self.list_tools(), "ttlMs": 604800000}}
        if method == "resources/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"resources": []}}
        if method == "prompts/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": []}}
        if method == "tools/call":
            params = request.get("params") or {}
            res = self.call_tool(params.get("name", ""), params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": req_id, "result": res}
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

    def serve_stdio(self) -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                if isinstance(req, dict):
                    resp = self.handle_request(req)
                    if resp is not None:
                        sys.stdout.write(json.dumps(resp) + "\n")
                        sys.stdout.flush()
            except Exception as exc:
                sys.stderr.write(f"Error: {exc}\n")


if __name__ == "__main__":
    CustomsLegalMcpServer().serve_stdio()
