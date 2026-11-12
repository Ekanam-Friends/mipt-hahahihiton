"""Выгрузка открытых регламентов МФТИ с mipt.ru.

Источники:
1. «Хранилище документов» (https://mipt.ru/docs) — JSON API `docsStorage.getTree`.
   Корневой запрос отдаёт плоский список всех элементов хранилища (~5.5 тыс.).
2. «Сведения об образовательной организации → Документы»
   (https://mipt.ru/sveden/document) — серверный HTML со ссылками на PDF.

Берём только кадровые/административные документы (то, о чём спросит сотрудник) плюс
несколько студенческих — для проверки уточняющих вопросов про роль.

Запуск:  python -m regnav.sources.mipt [--out data] [--dry-run]

Результат:
  data/raw/<id>.<ext>        исходные файлы (в .gitignore)
  data/manifest.jsonl        по строке на документ: название, тип, URL, sha256, fetched_at
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = "https://mipt.ru"
API = BASE + "/api/v1/"
UA = "Mozilla/5.0 (regnav corpus builder)"

# Темы, о которых спрашивает сотрудник. Регэксп по названию документа.
INCLUDE = re.compile(
    r"командирован|командировк|отпуск|оплат[аыу] труда|почасов|трудов(ого|ой|ых|ые) "
    r"(распорядк|договор|деятельност|спор)|распорядка|дистанционн(ой|ая|ую) работ|"
    r"дистанционный режим работы|совместительств|премир|преми[ий] |надбавк|коррупц|"
    r"конфликт[а-я]* интерес|подарк|охран[аыу] труда|персональных данных|"
    r"аттестации работников|увольнени|при[её]м[а-я]* на работу|кадров[а-я]* резерв|"
    r"подбору персонала|коллективный договор|отчислени|академическ[а-я]* отпуск|"
    r"стипенди",
    re.I,
)
# Шум, который совпадает по словам, но не про то: ГО/ЧС, аспирантские компетенции и т.п.
EXCLUDE = re.compile(
    r"НФГО|гражданской обороны|защите от ЧС|компетенци|образовательные стандарты|"
    r"Отчет о доработке|ОТЧЕТ О ПРОВЕДЕНИИ ИССЛЕДОВАНИЯ|Список фамилий|саббатикал|"
    r"Образец списка|Список научных трудов|самообследован|учреждении стипендии|"
    r"Scolarship|стипендии базовой|именных стипендий|Требования к разработке",
    re.I,
)
TYPES = {"Приказ", "Положение", "Регламент", "Инструкция", "Другое", None}
EXTS = {"pdf", "docx"}  # .doc (Word 97) без внешних утилит не разобрать — пропускаем

# Со страницы «Сведения» берём только эти документы (по подстроке в названии).
SVEDEN_PICK = re.compile(
    r"Правила внутреннего трудового распорядка|Коллективный договор|"
    r"Правила внутреннего распорядка обучающихся|академического и других видов отпусков|"
    r"порядке отчисления|Политика обработки персональных данных|"
    r"мер дисциплинарного взыскания",
    re.I,
)


def clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s).replace("\xa0", " ")
    return " ".join(s.split())


def fetch_storage(client: httpx.Client) -> list[dict]:
    r = client.get(API, params={"action": "docsStorage.getTree", "lang": "ru", "path": ""})
    r.raise_for_status()
    out = []
    for e in r.json()["elements"]:
        f = e.get("file") or {}
        title = clean(e.get("name", ""))
        ext = (f.get("ext") or "").lower()
        if not f.get("src") or ext not in EXTS or e.get("type") not in TYPES:
            continue
        if not INCLUDE.search(title) or EXCLUDE.search(title):
            continue
        out.append(
            {
                "id": f"st-{e['id']}",
                "title": title,
                "doc_type": e.get("type"),
                "uploaded_at": datetime.fromtimestamp(e["date"][0], timezone.utc).date().isoformat()
                if e.get("date")
                else None,
                "url": BASE + f["src"],
                "ext": ext,
                "source": "mipt.ru/docs",
            }
        )
    return out


def fetch_sveden(client: httpx.Client) -> list[dict]:
    from html.parser import HTMLParser

    links: list[tuple[str, str]] = []

    class P(HTMLParser):
        href: str | None = None
        buf: list[str] = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                self.href = dict(attrs).get("href")
                self.buf = []

        def handle_data(self, data):
            if self.href:
                self.buf.append(data)

        def handle_endtag(self, tag):
            if tag == "a" and self.href:
                links.append((self.href, clean(" ".join(self.buf))))
                self.href = None

    r = client.get(BASE + "/sveden/document")
    r.raise_for_status()
    P().feed(r.text)
    out, seen = [], set()
    for href, title in links:
        ext = href.rsplit(".", 1)[-1].lower()
        if ext not in EXTS or href in seen or not SVEDEN_PICK.search(title):
            continue
        seen.add(href)
        out.append(
            {
                "id": "sv-" + hashlib.md5(href.encode()).hexdigest()[:10],
                "title": title,
                "doc_type": None,
                "uploaded_at": None,
                "url": href if href.startswith("http") else BASE + href,
                "ext": ext,
                "source": "mipt.ru/sveden/document",
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="data")
    ap.add_argument("--dry-run", action="store_true", help="только список, без скачивания")
    args = ap.parse_args(argv)

    out = Path(args.out)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    with httpx.Client(headers={"User-Agent": UA}, timeout=60, follow_redirects=True) as client:
        docs = fetch_storage(client) + fetch_sveden(client)
        # Одинаковые файлы встречаются в хранилище по нескольку раз.
        uniq, seen = [], set()
        for d in docs:
            if d["url"] not in seen:
                seen.add(d["url"])
                uniq.append(d)
        print(f"отобрано {len(uniq)} документов", file=sys.stderr)
        if args.dry_run:
            for d in uniq:
                print(f"{d['id']}\t{d['ext']}\t{d['title']}")
            return 0

        manifest = []
        for i, d in enumerate(uniq, 1):
            path = raw / f"{d['id']}.{d['ext']}"
            if not path.exists():
                try:
                    r = client.get(d["url"])
                    r.raise_for_status()
                    path.write_bytes(r.content)
                    time.sleep(0.3)
                except httpx.HTTPError as e:
                    print(f"[{i}/{len(uniq)}] ОШИБКА {d['url']}: {e}", file=sys.stderr)
                    continue
            data = path.read_bytes()
            d.update(
                local_path=path.as_posix(),
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            manifest.append(d)
            print(f"[{i}/{len(uniq)}] {d['title'][:90]}", file=sys.stderr)

    # Дубликаты по содержимому (один файл под разными URL) — оставляем первый.
    by_hash, final = set(), []
    for d in manifest:
        if d["sha256"] not in by_hash:
            by_hash.add(d["sha256"])
            final.append(d)
    with open(out / "manifest.jsonl", "w", encoding="utf-8") as f:
        for d in final:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"готово: {len(final)} документов → {out / 'manifest.jsonl'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
