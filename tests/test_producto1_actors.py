"""Tests unitarios e integración para los 2 Actores Apify de Producto 1 (ETL + EDA)."""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from actors.apify_eda.my_actor.eda_core import (  # noqa: E402
    build_multisheet_xlsx_bytes,
    run_eda_pipeline,
)
from actors.apify_etl.my_actor.etl_core import (  # noqa: E402
    extraer_superficie_segura,
    normalize_drive_url,
    run_etl_pipeline,
)
from src.run_producto1_pipeline import (  # noqa: E402
    build_raw_consolidated_xlsx,
    run_producto1_end_to_end,
)


class TestActorsEstructuraApify:
    def test_archivos_requeridos_etl_y_eda(self):
        for actor_dir in (REPO_ROOT / "actors" / "apify_etl", REPO_ROOT / "actors" / "apify_eda"):
            assert (actor_dir / "Dockerfile").is_file()
            assert (actor_dir / "requirements.txt").is_file()
            assert (actor_dir / ".actor" / "actor.json").is_file()
            assert (actor_dir / ".actor" / "input_schema.json").is_file()
            assert (actor_dir / ".actor" / "dataset_schema.json").is_file()
            assert (actor_dir / ".actor" / "output_schema.json").is_file()
            assert (actor_dir / "my_actor" / "main.py").is_file()
            assert (actor_dir / "my_actor" / "__main__.py").is_file()


class TestUtilidadesETL:
    def test_normalize_drive_url(self):
        url = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/view?usp=sharing"
        assert normalize_drive_url(url) == "https://drive.google.com/uc?export=download&confirm=t&id=1AbCdEfGhIjKlMnOpQrStUvWxYz"
        sheet_url = "https://docs.google.com/spreadsheets/d/1SheetIdXYZ123/edit?gid=4567#gid=4567"
        assert normalize_drive_url(sheet_url) == "https://docs.google.com/spreadsheets/d/1SheetIdXYZ123/export?format=csv&gid=4567"
        assert normalize_drive_url(sheet_url, output_format="xlsx") == "https://docs.google.com/spreadsheets/d/1SheetIdXYZ123/export?format=xlsx"
        assert normalize_drive_url("https://example.com/data.csv") == "https://example.com/data.csv"

    def test_extraer_superficie_ignora_distancias(self):
        assert extraer_superficie_segura("Lote a 300 metros del rio, 1200 m2 totales") == 1200.0
        assert extraer_superficie_segura("Fraccion de 1.5 ha en Calamuchita") == 15000.0


class TestPipelineProducto1EndToEnd:
    def test_libro_unico_raw_consolidado_etl_y_eda(self, tmp_path: Path):
        wb_path = build_raw_consolidated_xlsx(tmp_path / "dataset_raw_consolidado.xlsx")
        assert wb_path.is_file()

        df_clean, _ = run_etl_pipeline(raw_workbook_source=str(wb_path))
        assert len(df_clean) == 894

        clean_csv = tmp_path / "clean.csv"
        df_clean.to_csv(clean_csv, index=False, encoding="utf-8")
        eda_res = run_eda_pipeline(
            dataset_limpio_source=str(clean_csv),
            raw_workbook_source=str(wb_path),
        )
        assert eda_res["summary"]["total_lotes_limpios"] == 894
        assert eda_res["summary"]["oportunidades_p1"] == 244

    def test_etl_y_eda_sobre_datos_reales(self, tmp_path: Path):
        res = run_producto1_end_to_end(processed_dir=tmp_path, top_oportunidades_limit=100)
        csv_limpio = Path(res["dataset_limpio_csv"])
        csv1 = Path(res["csv_1"])
        csv2 = Path(res["csv_2"])
        csv3 = Path(res["csv_3"])
        xlsx = Path(res["xlsx"])

        assert csv_limpio.is_file()
        assert csv1.is_file()
        assert csv2.is_file()
        assert csv3.is_file()
        assert xlsx.is_file()

        assert res["summary"]["total_lotes_limpios"] >= 700
        assert res["summary"]["oportunidades_p1"] > 0

        # Verificar que el .xlsx contiene hoja1, hoja2 y hoja3 válidas
        with zipfile.ZipFile(xlsx, "r") as zf:
            names = set(zf.namelist())
            assert "xl/workbook.xml" in names
            assert "xl/worksheets/sheet1.xml" in names
            assert "xl/worksheets/sheet2.xml" in names
            assert "xl/worksheets/sheet3.xml" in names
            wb_xml = ET.fromstring(zf.read("xl/workbook.xml"))
            ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            sheet_names = [s.attrib["name"] for s in wb_xml.findall(".//m:sheet", ns)]
            assert sheet_names == ["hoja1", "hoja2", "hoja3"]

    def test_sin_np_random_en_actores(self):
        for p in (
            REPO_ROOT / "actors" / "apify_etl" / "my_actor" / "etl_core.py",
            REPO_ROOT / "actors" / "apify_eda" / "my_actor" / "eda_core.py",
        ):
            assert "np.random" not in p.read_text(encoding="utf-8")