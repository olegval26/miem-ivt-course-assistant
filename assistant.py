"""Помощник по программам первого курса ИВТ МИЭМ."""
import argparse
from collections import Counter
from dataclasses import dataclass
import json
from math import log
from pathlib import Path
import re
import sys

import snowballstemmer

CATALOG = "https://www.hse.ru/ba/isct/courses?course=1.1.1.4&page=1&year=2026"
YEAR = "2026/2027"
STEMMER = snowballstemmer.stemmer("russian")
WORDS = re.compile(r"[а-яa-z0-9]+(?:\+\+)?", re.I)
STOP = set(
    "а и в во из за на от до к по про у о об для с со это эти он она они как какой какая какие "
    "чем что кто где ли есть мне мы их или но чтобы еще когда можно если курс курсе "
    "изучают изучается найти модуль модуля содержание темы входят относится прочитать".split()
)


def normalize(text):
    return text.lower().replace("ё", "е").replace("‑", "-")


def tokens(text):
    words = WORDS.findall(normalize(text))
    return [word for word in words if word not in STOP]


def stems(text):
    return STEMMER.stemWords(tokens(text))


@dataclass(frozen=True)
class Answer:
    text: str
    sources: tuple
    status: str = "answer"

    def render(self):
        links = "\n".join(f"- {title} — {url}" for title, url in self.sources)
        return f"{self.text}\n\nИсточники\n{links}"


class Assistant:
    def __init__(self):
        self.courses = json.loads(Path(__file__).with_name("courses.json").read_text(encoding="utf-8"))
        self.index = [Counter(stems(course["title"] + " " + " ".join(course["topics"]))) for course in self.courses]
        self.frequency = Counter(word for document in self.index for word in document)
        self.avg_length = sum(map(Counter.total, self.index)) / len(self.index)

    def answer(self, question):
        q = normalize(question.strip())
        if not tokens(q):
            return self.unknown("Задайте вопрос по дисциплине первого курса.")
        if re.search(r"\b20\d\d\s*[/–-]\s*20\d\d\b", q) and not re.search(r"2026\s*[/–-]\s*2027", q):
            return self.unknown("В базе только программы 2026/2027 учебного года.")
        if re.search(r"\b(?:[2-6](?:-й|-го)?|второго|третьего|четвертого)\s+курс", q):
            return self.unknown("В базе только дисциплины первого курса.")
        named = self.named_courses(q)
        if re.search(r"расписани|аудитори|на этой неделе|сегодня|завтра|пересдач|балл.{0,12}(?:выстав|получил)", q):
            return self.unknown("В программах нет актуального расписания, условий конкретной пересдачи или персональных оценок.", named)
        if re.search(r"формальн.{0,12}(?:пререквизит|предпосыл)|официальн.{0,20}пререквизит", q):
            return self.unknown("Индекс тем не позволяет подтвердить официальный пререквизит.", named, "sections")
        if re.search(r"\b(?:посчитай|вычисли|рассчитай)\b", q):
            return self.unknown("Прототип показывает формулы из программ. Вычисление индивидуальной оценки не поддерживается.", named, "intermediate_certification")

        compare = re.search(r"сравн|общ(?:его|ие темы)|пересек|пересеч|связ|отлич", q)
        if compare and len(named) == 2:
            return self.compare(*named, differences=bool(re.search(r"отлич|сравн", q)))
        if len(named) > 1:
            return self.unknown("Уточните одну дисциплину или попросите сравнить две: " +
                                "; ".join(course["title"] for course in named) + ".", named, status="clarify")
        if not named:
            if re.search(r"формул|вес|коэффициент|литератур|учебник|книг|преподавател|кредит|на каком модуле", q):
                return self.unknown("Укажите название дисциплины.", status="clarify")
            return self.search_topics(q)
        course = named[0]
        if re.search(r"формул|вес|коэффициент|оценк|оценив|оценива|процент", q):
            return self.grading(course, q)
        if re.search(r"литератур|учебник|книг|почитать", q):
            return self.literature(course, q)
        if re.search(r"контрол|лаборатор|блокирующ|тестир|экзамен", self.without_name(q, course)):
            return self.control(course, q)
        if re.search(r"преподавател|кто вед|кто чита", q):
            people = "; ".join(course["teachers"])
            return self.result(course, f"Преподаватели — {people}.") if people else self.unknown(
                "В карточке не перечислены преподаватели.", [course])
        if re.search(r"кредит|зачетн.{0,3} единиц", q):
            return self.result(course, f"Количество кредитов — {course['credits']}.") if course["credits"] else self.unknown(
                "В карточке не указано число кредитов.", [course])
        if re.search(r"модул|когда чита|когда проход|обязательн|статус", q):
            return self.result(course, f"{course['title']} — {course['period']}. {course['status']}.")
        if not course["topics"]:
            return self.unknown("На карточке нет опубликованного раздела с темами.", [course])
        terms = set(stems(self.without_name(q, course)))
        matches = self.topic_matches(course, terms)
        if matches:
            return self.result(course, "В программе есть следующие темы: " + "; ".join(matches) + ".", "sections")
        if re.search(r"\bли\b", self.without_name(q, course)) and terms:
            return self.unknown("Эта тема явно не найдена в проиндексированных разделах программы.", [course], "sections")
        return self.result(course, "Основные темы: " + "; ".join(course["topics"]) + ".", "sections")

    def named_courses(self, q):
        aliases = {
            "1197128651": ("матан", "матанализ"),
            "1197128559": ("дискретка", "дискрет"),
            "1197128565": ("алгопрога", "аип"),
            "1197128535": ("инженерка", "инженерная графика"),
            "1197128547": ("python в науке о данных", "питон в науке о данных"),
            "1197128553": ("управление продуктами и проектами",),
            "1163619144": ("английский независимый экзамен", "независимый экзамен по английскому"),
        }
        variants = ("углублен", "индустриальн")
        normalized = " " + " ".join(stems(q)) + " "
        hits = []
        for course in self.courses:
            title = course["title"].split(" (")[0].lower()
            matching = (title, *aliases.get(course["url"].split("/")[-1].split(".")[0], ()))
            for name in matching:
                phrase = " ".join(stems(name))
                match = re.search(r"(?<!\S)" + re.escape(phrase) + r"(?!\S)", normalized)
                if not match:
                    continue
                variant = next((prefix for prefix in variants if prefix in course["title"]), "")
                vicinity = normalized[max(0, match.start() - 28):match.end() + 32]
                requested = next((prefix for prefix in variants if prefix in vicinity), "")
                if requested and not variant and ("обычн" in vicinity or "базов" in vicinity):
                    requested = ""
                if variant == requested or (variant and variant == next(
                    (prefix for prefix in variants if prefix in normalized), "") and
                    re.search(r"сравн|отлич|пересек|общ", q) and re.search(r"обычн|базов", q)):
                    hits.append((match.start(), match.end(), course))
                    break
        hits.sort(key=lambda hit: (hit[0], -hit[1]))
        return [course for start, end, course in hits if not any(
            other_start <= start and other_end >= end and other_end - other_start > end - start
            for other_start, other_end, _ in hits
        )]

    @staticmethod
    def without_name(q, course):
        title = course["title"].split(" (")[0]
        question_words = list(WORDS.finditer(q))
        title_words = stems(title)
        for i, token in enumerate(question_words):
            last = i + len(title_words) - 1
            if last < len(question_words) and stems(q[token.start():question_words[last].end()]) == title_words:
                return q[:token.start()] + " " + q[question_words[last].end():]
        return q

    def search_topics(self, q):
        terms = {word for word in stems(q) if word in self.frequency}
        if not terms:
            return self.unknown("Подходящих тем в программах не найдено. Уточните дисциплину или формулировку.")
        scores = []
        for course, doc in zip(self.courses, self.index):
            matched = terms & doc.keys()
            if not matched:
                continue
            norm = 0.25 + 0.75 * doc.total() / self.avg_length
            score = sum(
                log(1 + (len(self.index) - self.frequency[word] + 0.5) / (self.frequency[word] + 0.5))
                * (2.2 * doc[word]) / (doc[word] + 1.2 * norm)
                for word in matched
            )
            matches = self.topic_matches(course, terms)
            if matches:
                scores.append((score, course, matches))
        if not scores:
            return self.unknown("Подходящих фрагментов в программах не найдено.")
        scores.sort(key=lambda row: row[0], reverse=True)
        selected = [(c, matches) for score, c, matches in scores if score >= scores[0][0] * 0.70][:3]
        lines = [f"{course['title']} — {', '.join(matches)}." for course, matches in selected]
        return Answer("\n".join(lines), tuple(self.source(c, "sections") for c, _ in selected))

    @staticmethod
    def topic_matches(course, terms):
        ranked = [(len(terms & set(stems(topic))), topic) for topic in course["topics"]]
        ranked.sort(key=lambda row: row[0], reverse=True)
        return [topic for score, topic in ranked if score and score >= ranked[0][0] - 1][:4]

    def grading(self, course, q):
        formulas = course["grading"]
        module = re.search(r"\b(\d+)(?:-?(?:й|м|го|ом))?\s*модул|модул\w*\s*(\d+)\b", q)
        if module:
            number = module[1] or module[2]
            formulas = {number: formulas[number]} if number in formulas else {}
        elif ordinal := re.search(r"\b(перв|втор|трет|четверт)\w*\s+модул", q):
            number = {"перв": "1", "втор": "2", "трет": "3", "четверт": "4"}[ordinal[1]]
            formulas = {number: formulas[number]} if number in formulas else {}
        if not formulas:
            return self.unknown("Для указанной дисциплины и модуля в программе 2026/2027 нет опубликованной формулы.", [course], "intermediate_certification")
        lines = [f"{number}-й модуль — {formula}" for number, formula in sorted(formulas.items())]
        return self.result(course, "\n".join(lines), "intermediate_certification")

    def literature(self, course, q):
        extra = bool(re.search(r"дополнительн", q))
        main = bool(re.search(r"основн", q))
        keys = ("extra",) if extra and not main else ("required",) if main and not extra else ("required", "extra")
        lines = []
        for key in keys:
            books = course[key]
            if books:
                label = "Основная" if key == "required" else "Дополнительная"
                suffix = f" (+{len(books) - 3} в источнике)" if len(books) > 3 else ""
                lines.append(label + " — " + "; ".join(books[:3]) + suffix + ".")
        if not lines:
            return self.unknown("Запрошенный раздел литературы не заполнен в публичной карточке.", [course], "library")
        return self.result(course, "\n".join(lines), "library")

    def control(self, course, q):
        controls = course["controls"]
        if "блокирующ" in q:
            controls = [item for item in controls if item["status"] == "блокирующий"]
        if not controls:
            return self.unknown("В карточке нет подходящих опубликованных элементов контроля.", [course], "controls")
        labels = list(dict.fromkeys(item["name"] for item in controls))
        suffix = f" (+{len(labels) - 6} в источнике)" if len(labels) > 6 else ""
        return self.result(course, "Элементы контроля — " + "; ".join(labels[:6]) + suffix + ".", "controls")

    def compare(self, first, second, differences=False):
        if not first["topics"] or not second["topics"]:
            return self.unknown("Для сравнения нужны опубликованные темы обеих дисциплин.", [first, second])
        first_topics = {topic.casefold() for topic in first["topics"]}
        second_topics = {topic.casefold() for topic in second["topics"]}
        common = [topic for topic in first["topics"] if topic.casefold() in second_topics]
        sources = (self.source(first, "sections"), self.source(second, "sections"))
        lines = [f"{first['title']} и {second['title']}."]
        if common:
            lines.append("Общие темы — " + "; ".join(common) + ".")
        elif not differences:
            return self.unknown("В индексе нет совпадающих тем для подтверждения связи.", [first, second], "sections")
        if differences:
            for course, other_topics in ((first, second_topics), (second, first_topics)):
                distinct = [topic for topic in course["topics"] if topic.casefold() not in other_topics][:3]
                if distinct:
                    lines.append(f"Среди тем дисциплины «{course['title']}» — " + "; ".join(distinct) + ".")
        if len(lines) == 1:
            lines.append("Сводки тем совпадают. Для сравнения деталей откройте программы обеих дисциплин.")
        return Answer("\n".join(lines), sources)

    @staticmethod
    def source(course, section=""):
        return course["title"], course["url"] + ("#" + section if section in course["sections"] else "")

    def result(self, course, text, section=""):
        return Answer(text, (self.source(course, section),))

    def unknown(self, text, courses=(), section="", status="unknown"):
        sources = tuple(self.source(course, section) for course in courses) or (("Каталог ВШЭ, 1-й курс 2026/2027", CATALOG),)
        return Answer(text, sources, status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="*", help="вопрос в кавычках или несколькими словами")
    args = parser.parse_args()
    bot = Assistant()
    if args.question:
        print(bot.answer(" ".join(args.question)).render())
    elif sys.stdin.isatty():
        print("ИВТ МИЭМ, 1-й курс 2026/2027. Введите вопрос. Для выхода — Ctrl+D.")
        try:
            while True:
                print(bot.answer(input("\n> ")).render())
        except (EOFError, KeyboardInterrupt):
            print()
    else:
        for line in sys.stdin:
            if line.strip():
                print(bot.answer(line).render(), end="\n\n")


if __name__ == "__main__":
    main()
