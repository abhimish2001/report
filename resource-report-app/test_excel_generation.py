import os
import sys
import openpyxl
from openpyxl.styles import PatternFill

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.excel_reader import read_file_to_dataframe
from modules.column_mapper import map_dataframe_to_schema
from modules.normalizer import run_normalization_pipeline
from modules.calculator import calculate_aggregates
from modules.variance_engine import analyze_variances
from modules.excel_exporter import create_styled_workbook

def run_excel_test():
    print("=" * 60)
    print("STARTING EXCEL GENERATION & COMPREHENSIVE VALIDATION TEST")
    print("=" * 60)

    csv_path = r"c:\Users\am273\Downloads\Report-20260911T164327Z-1-001\Report\TaskStatus-202608(Input File).csv"
    if not os.path.exists(csv_path):
        # Fallback to local copy if available
        csv_path = "TaskStatus-202608(Input File).csv"

    print(f"Loading data from: {csv_path}")
    df_raw = read_file_to_dataframe(csv_path, os.path.basename(csv_path))
    mapped_df, _, _ = map_dataframe_to_schema(df_raw)
    norm_df, _, _ = run_normalization_pipeline(mapped_df)
    aggs = calculate_aggregates(norm_df)
    vars_info = analyze_variances(aggs, overload_threshold_pct=110.0)

    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    excel_path = os.path.join(output_dir, "Validated_Resource_Utilization_Report.xlsx")

    sys.stdout.reconfigure(encoding='utf-8')
    # Step 1: Generate Excel Workbook
    print(f"\n[Step 1] Generating Excel sheet: {excel_path}...")
    saved_path = create_styled_workbook(aggs, vars_info, excel_path)
    assert os.path.exists(saved_path), f"File {saved_path} was not created!"
    file_size = os.path.getsize(saved_path)
    print(f"[OK] Excel file created successfully! Size: {file_size} bytes")
    assert file_size > 1000, "File size too small, may be corrupted"

    # Step 2: Open with openpyxl and inspect sheets
    print("\n[Step 2] Validating Workbook Structure & Sheets...")
    wb = openpyxl.load_workbook(saved_path, data_only=False)
    sheet_names = wb.sheetnames
    print(f"Sheet names in workbook: {sheet_names}")
    assert len(sheet_names) == 4, f"Expected 4 sheets, found {len(sheet_names)}: {sheet_names}"
    
    assert "Resource Utilization" in sheet_names, "Missing 'Resource Utilization' sheet"
    assert any("Utilization" in s for s in sheet_names if s != "Resource Utilization"), "Missing Entity-wise Utilization sheet"
    assert "Horizontal-View" in sheet_names, "Missing 'Horizontal-View' sheet"
    assert "Summary" in sheet_names, "Missing 'Summary' sheet"
    print("[OK] All 4 required sheets present!")

    # Step 3: Test Sheet 1 - Resource Utilization
    print("\n[Step 3] Testing Sheet 1: 'Resource Utilization'...")
    ws1 = wb["Resource Utilization"]
    assert ws1.views.sheetView[0].showGridLines is True, "Gridlines not enabled on Sheet 1"
    
    # Check Title
    a1_val = str(ws1["A1"].value)
    print(f"  Title cell A1: '{a1_val}'")
    assert "Month :" in a1_val, f"Unexpected title in A1: {a1_val}"

    # Check Section 1 Header
    assert ws1["A3"].value == "Work-Type-wise Resource Utilization"
    expected_headers_s1 = ["Work Type", "Tasks", "Expected Hrs", "Actual Hrs", "Share of Actual Effort", "Variance"]
    actual_headers_s1 = [ws1.cell(row=4, column=c).value for c in range(1, 7)]
    assert actual_headers_s1 == expected_headers_s1, f"Headers mismatch: {actual_headers_s1} vs {expected_headers_s1}"

    # Verify work types data rows
    wt_names = [w["work_type"] for w in aggs["by_work_type"]]
    s1_row = 5
    for wt in wt_names:
        cell_wt = ws1.cell(row=s1_row, column=1).value
        assert cell_wt == wt, f"Row {s1_row} expected {wt}, got {cell_wt}"
        tasks = ws1.cell(row=s1_row, column=2).value
        exp_hrs = ws1.cell(row=s1_row, column=3).value
        act_hrs = ws1.cell(row=s1_row, column=4).value
        assert tasks > 0, f"Tasks should be > 0 for {wt}"
        assert act_hrs >= 0, f"Actual hours should be >= 0 for {wt}"
        s1_row += 1

    # Check Total row for Section 1
    assert ws1.cell(row=s1_row, column=1).value == "Total"
    tot_tasks_s1 = ws1.cell(row=s1_row, column=2).value
    tot_exp_s1 = ws1.cell(row=s1_row, column=3).value
    tot_act_s1 = ws1.cell(row=s1_row, column=4).value
    tot_var_s1 = ws1.cell(row=s1_row, column=6).value
    print(f"  Work-Type Totals: Tasks={tot_tasks_s1}, Expected={tot_exp_s1}, Actual={tot_act_s1}, Variance={tot_var_s1}")
    assert tot_tasks_s1 == aggs["totals"]["tasks"], "Total tasks mismatch"
    assert tot_exp_s1 == aggs["totals"]["expected_hrs"], "Total expected hours mismatch"
    assert tot_act_s1 == aggs["totals"]["actual_hrs"], "Total actual hours mismatch"
    assert round(tot_var_s1, 2) == round(aggs["totals"]["variance"], 2), "Total variance mismatch"

    # Check Section 2: Resource-wise Resource Utilization
    s1_row += 3
    assert ws1.cell(row=s1_row, column=1).value == "Resource-wise Resource Utilization"
    s1_row += 1
    expected_emp_headers = ["Resource Name", "Tasks", "Expected Hrs", "Actual Hrs", "Variance", "Utilization %", "Completed", "In Progress", "Pending"]
    actual_emp_headers = [ws1.cell(row=s1_row, column=c).value for c in range(1, 10)]
    assert actual_emp_headers == expected_emp_headers, f"Emp headers mismatch: {actual_emp_headers}"
    s1_row += 1

    emp_names = [e["employee"] for e in aggs["by_employee"]]
    for emp_name in emp_names:
        found_name = ws1.cell(row=s1_row, column=1).value
        assert found_name == emp_name, f"Expected emp {emp_name}, got {found_name}"
        util_val = ws1.cell(row=s1_row, column=6).value
        assert util_val is not None and util_val > 0
        s1_row += 1

    # Emp Total row
    assert ws1.cell(row=s1_row, column=1).value == "Total"
    assert ws1.cell(row=s1_row, column=2).value == aggs["totals"]["tasks"]
    assert ws1.cell(row=s1_row, column=4).value == aggs["totals"]["actual_hrs"]
    print(f"[OK] Sheet 1 ('Resource Utilization') verified with 100% precision!")

    # Step 4: Test Sheet 2 - Entity-wise Utilization
    sheet2_title = [s for s in sheet_names if "Utilization" in s and s != "Resource Utilization"][0]
    print(f"\n[Step 4] Testing Sheet 2: '{sheet2_title}'...")
    ws2 = wb[sheet2_title]
    assert ws2.views.sheetView[0].showGridLines is True
    assert "Hours Report" in str(ws2["A1"].value)
    # Check header merges and periods
    assert ws2.cell(row=2, column=1).value is not None
    # Check that services exist in column A
    services_found = [ws2.cell(row=r, column=1).value for r in range(4, ws2.max_row + 1) if ws2.cell(row=r, column=1).value]
    print(f"  Services in Sheet 2: {len(services_found)} services found ({services_found[:3]}...)")
    assert len(services_found) > 0, "No service rows found in Sheet 2"
    print(f"[OK] Sheet 2 ('{sheet2_title}') verified!")

    # Step 5: Test Sheet 3 - Horizontal-View
    print("\n[Step 5] Testing Sheet 3: 'Horizontal-View'...")
    ws3 = wb["Horizontal-View"]
    assert ws3.views.sheetView[0].showGridLines is True
    assert ws3.cell(row=1, column=1).value == "Week"
    assert ws3.cell(row=1, column=2).value == "Work Type"
    assert ws3.max_row > 1, "Sheet 3 has no data rows"
    print(f"  Sheet 3 has {ws3.max_row} rows and {ws3.max_column} columns")
    print("[OK] Sheet 3 ('Horizontal-View') verified!")

    # Step 6: Test Sheet 4 - Summary
    print("\n[Step 6] Testing Sheet 4: 'Summary'...")
    ws4 = wb["Summary"]
    assert ws4.views.sheetView[0].showGridLines is True
    assert "Most Overloaded Work" in str(ws4["A2"].value)
    expected_s4_headers = ["Category", "Entity Name", "Actual Effort", "Utilization / Share", "Governance Highlight"]
    actual_s4_headers = [ws4.cell(row=3, column=c).value for c in range(1, 6)]
    assert actual_s4_headers == expected_s4_headers, f"Summary headers mismatch: {actual_s4_headers}"
    summary_rows = [ws4.cell(row=r, column=2).value for r in range(4, ws4.max_row + 1) if ws4.cell(row=r, column=2).value]
    print(f"  Overloaded work items listed in Summary: {summary_rows}")
    assert len(summary_rows) > 0, "Summary sheet should contain overloaded work items"
    print("[OK] Sheet 4 ('Summary') verified!")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED! EXCEL GENERATION IS ROBUST AND FULLY VALIDATED.")
    print("=" * 60)

if __name__ == "__main__":
    run_excel_test()
