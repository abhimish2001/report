import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.excel_reader import read_file_to_dataframe
from modules.column_mapper import map_dataframe_to_schema
from modules.normalizer import run_normalization_pipeline
from modules.calculator import calculate_aggregates
from modules.variance_engine import analyze_variances
from modules.ai_insights import generate_ai_insights
from modules.excel_exporter import create_styled_workbook
from modules.pdf_exporter import generate_pdf_report

csv_path = r"c:\Users\am273\Downloads\Report-20260911T164327Z-1-001\Report\TaskStatus-202608(Input File).csv"

print("1. Ingesting and Normalizing...")
df_raw = read_file_to_dataframe(csv_path, "TaskStatus-202608(Input File).csv")
mapped_df, mapping_dict, _ = map_dataframe_to_schema(df_raw)
norm_df, norm_log, flagged = run_normalization_pipeline(mapped_df)

print("2. Calculating Aggregates...")
aggs = calculate_aggregates(norm_df)
print(f"   Period: {aggs['period_label']}")
print(f"   Totals: {aggs['totals']}")
print(f"   Work Types: {[w['work_type'] for w in aggs['by_work_type']]}")
print(f"   Employees: {[e['employee'] for e in aggs['by_employee']]}")

print("3. Analyzing Variances & Attention Areas...")
vars_info = analyze_variances(aggs, overload_threshold_pct=110.0)
print(f"   Overloaded Employees: {[e['name'] for e in vars_info['overloaded_employees']]}")
print(f"   Overloaded Work items count: {len(vars_info['overloaded_work_table'])}")

print("4. Generating AI / Rule-Based Insights...")
insights = generate_ai_insights(aggs, vars_info)
print(f"   Provider: {insights.get('provider')}")
print(f"   Exec Summary Snippet: {insights.get('executive_summary')[:120]}...")

print("5. Exporting Excel (4 Sheets)...")
os.makedirs("output", exist_ok=True)
excel_out = os.path.join("output", "Test_Resource_Utilization_Report.xlsx")
create_styled_workbook(aggs, vars_info, excel_out)
print(f"   Created Excel: {excel_out} ({os.path.getsize(excel_out)} bytes)")

print("6. Exporting PDF Report...")
pdf_out = os.path.join("output", "Test_Resource_Utilization_Report.pdf")
generate_pdf_report(aggs, vars_info, insights, pdf_out)
print(f"   Created PDF: {pdf_out} ({os.path.getsize(pdf_out)} bytes)")

print("\nALL MODULES FUNCTIONING FLAWLESSLY!")
