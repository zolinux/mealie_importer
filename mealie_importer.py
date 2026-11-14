#!/usr/bin/env python3
"""
Mealie Recipe Importer - Import recipes from mindmegette.hu to Mealie
Supports both MHTML files and direct web scraping
"""

import argparse
import csv
import json
import os
import re
import sys
import unicodedata

if sys.version_info >= (3, 10):
    import truststore

    truststore.inject_into_ssl()

import requests
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import mimetypes

# Set output encoding to UTF-8
if sys.stdout.encoding.lower() != 'utf-8':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

# Configuration
PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"

if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value

MEALIE_URL = os.getenv("MEALIE_URL", "").strip().rstrip("/")
TOKEN = os.getenv("MEALIE_TOKEN", "").strip()
MHTML_FILE = os.getenv("MHTML_FILE", "").strip()
RECIPE_URLS = [
    url.strip()
    for url in os.getenv("RECIPE_URLS", "").split(",")
    if url.strip()
]
verify_ssl_value = os.getenv("MEALIE_VERIFY_SSL", "true").strip().lower()
if verify_ssl_value not in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
    raise ValueError("MEALIE_VERIFY_SSL must be a boolean value")
MEALIE_VERIFY_SSL = verify_ssl_value in {"1", "true", "yes", "on"}

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

IMAGE_HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
}


def parse_bookmark_folder(filepath: str, folder_name: str) -> List[Dict[str, str]]:
    """Return all links contained in the named Netscape bookmark folder."""
    soup = BeautifulSoup(Path(filepath).read_bytes(), "html.parser")
    folder_heading = next(
        (
            heading
            for heading in soup.find_all("h3")
            if heading.get_text(" ", strip=True).casefold() == folder_name.casefold()
        ),
        None,
    )
    if folder_heading is None:
        raise ValueError(f'Bookmark folder "{folder_name}" was not found')

    folder_contents = folder_heading.find_next("dl")
    if folder_contents is None:
        raise ValueError(f'Bookmark folder "{folder_name}" has no contents')

    return [
        {"title": link.get_text(" ", strip=True), "url": link.get("href", "").strip()}
        for link in folder_contents.find_all("a")
        if link.get("href", "").strip()
    ]


def is_recipe_category_label(value: str) -> bool:
    return bool(re.search(r"(?:rezepte|recipes)\s*$", value, re.I))


class MealieRecipeImporter:
    def __init__(
        self, base_url: Optional[str] = None, token: Optional[str] = None
    ):
        self.base_url = (base_url or MEALIE_URL).rstrip("/")
        self.token = token or TOKEN
        if not self.base_url:
            raise ValueError("MEALIE_URL not found in environment or .env file")
        if not self.token:
            raise ValueError("MEALIE_TOKEN not found in environment or .env file")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        self.session.headers.update({"Accept": "application/json"})
        self.session.verify = MEALIE_VERIFY_SSL
        import urllib3
        if not self.session.verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def parse_mhtml_file(self, filepath: str) -> Dict[str, Any]:
        """
        Parse MHTML file and extract recipe content
        """
        from email.parser import BytesParser
        from email.policy import EmailPolicy
        import quopri
        
        with open(filepath, "rb") as f:
            content = f.read()

        # Parse MHTML as email message
        parser = BytesParser()
        msg = parser.parsebytes(content)

        # Find the HTML part
        html_content = None
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                html_content = payload.decode("utf-8", errors="ignore")
                break

        if not html_content:
            raise ValueError("Could not find HTML content in MHTML file")

        # Parse with BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Extract recipe data
        recipe = self._extract_recipe_from_html(soup)
        return recipe

    def _extract_recipe_from_html(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        Extract recipe data from Schema.org JSON-LD or common HTML conventions.
        """
        schema_recipe = self._extract_jsonld_recipe(soup)

        recipe = {
            "name": "",
            "description": "",
            "ingredients": [],
            "instructions": [],
            "servings": 1,
            "recipeYield": 1,
            "tags": []
        }

        post_title = soup.select_one(".post-title.entry-title")
        title = post_title or soup.find(
            "h1", {"class": re.compile(".*title.*", re.I)}
        )
        if not title:
            title = soup.find("h1")
        if not title:
            title = soup.find("h2")
        if title:
            recipe["name"] = title.get_text(strip=True)
        if not recipe["name"] or recipe["name"].casefold() in {
            "oldalak", "home", "homepage",
        }:
            title_meta = soup.find("meta", property="og:title")
            if title_meta and title_meta.get("content"):
                recipe["name"] = title_meta["content"].strip()
        if not recipe["name"]:
            name_meta = soup.find(attrs={"itemprop": "name"})
            if name_meta:
                recipe["name"] = (
                    name_meta.get("content")
                    or name_meta.get_text(" ", strip=True)
                )

        # Look for ingredients - check for wrapper with ingredients
        ingredients_wrapper = soup.find("div", {"class": re.compile(".*ingredients.*wrapper.*", re.I)})
        
        if ingredients_wrapper:
            # Find all ingredient items
            for item in ingredients_wrapper.find_all("div", {"class": re.compile(".*ingredients.*meta.*", re.I)}):
                ingredient_parts = []
                
                # Get amount (strong tag)
                strong = item.find("strong")
                if strong:
                    ingredient_parts.append(strong.get_text(strip=True))
                
                # Get unit (span)
                span = item.find("span")
                if span:
                    ingredient_parts.append(span.get_text(strip=True))
                
                # Get ingredient name (link)
                link = item.find("a", {"class": re.compile(".*ingredient.*link.*", re.I)})
                if link:
                    ingredient_parts.append(link.get_text(strip=True))
                
                if ingredient_parts:
                    ingredient_text = " ".join(ingredient_parts)
                    recipe["ingredients"].append({
                        "original": ingredient_text
                    })

        if not recipe["ingredients"]:
            recipe["ingredients"] = [
                {
                    "original": (
                        item.get("content") or item.get_text(" ", strip=True)
                    ).strip()
                }
                for item in soup.select('[itemprop~="recipeIngredient"]')
                if (
                    item.get("content") or item.get_text(" ", strip=True)
                ).strip()
            ]

        if not recipe["ingredients"]:
            ingredient_headings = (
                "hozzávalók", "zutaten", "ingredients", "ingredient list",
                "zutatenliste", "ingredienser",
            )
            for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5"]):
                if not any(
                    label in heading.get_text(" ", strip=True).casefold()
                    for label in ingredient_headings
                ):
                    continue
                for following in heading.find_all_next(
                    ["h2", "h3", "h4", "h5", "ul", "ol"]
                ):
                    if following.name in {"h2", "h3", "h4", "h5"}:
                        if int(following.name[1]) <= int(heading.name[1]):
                            break
                        continue
                    recipe["ingredients"] = [
                        {"original": text}
                        for item in following.find_all("li")
                        if (
                            text := item.get_text(" ", strip=True)
                        )
                        and not re.match(
                            r"(?:előkészítés|sütés|összesen)\s*:",
                            text,
                            re.I,
                        )
                    ]
                    if recipe["ingredients"]:
                        break
                if recipe["ingredients"]:
                    break
        if not recipe["ingredients"]:
            for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5"]):
                if not any(
                    label in heading.get_text(" ", strip=True).casefold()
                    for label in ingredient_headings
                ):
                    continue
                for section in heading.parent.find_next_siblings():
                    if section.name in {"h2", "h3", "h4", "h5"}:
                        break
                    rows = section.find_all(
                        "div",
                        class_=lambda classes: classes
                        and "my-2" in classes
                        and "text-lg" in classes,
                    )
                    if rows:
                        recipe["ingredients"] = [
                            {"original": row.get_text(" ", strip=True)}
                            for row in rows
                            if row.get_text(" ", strip=True)
                        ]
                        break
                if recipe["ingredients"]:
                    break

        if not recipe["ingredients"]:
            for container in soup.select("div.grid-cols-2"):
                rows = container.select("div.my-2.text-lg")
                if (
                    not rows
                    or not container.find("h5")
                    or not container.select_one('input[type="checkbox"]')
                ):
                    continue
                seen = set()
                for row in rows:
                    text = row.get_text(" ", strip=True)
                    if text and text not in seen:
                        seen.add(text)
                        recipe["ingredients"].append({"original": text})
                if recipe["ingredients"]:
                    break

        # Look for instructions - check for recipe-instructions class
        instructions_heading = next(
            (
                heading
                for heading in soup.find_all(["h1", "h2", "h3", "h4"])
                if any(
                    label in heading.get_text(" ", strip=True).casefold()
                    for label in (
                        "elkészítés", "zubereitung", "anleitung", "instructions",
                        "preparation", "method", "rezeptzubereitung",
                    )
                )
            ),
            None,
        )
        if instructions_heading:
            instruction_box = instructions_heading.find_next("mindmegette-wysiwyg-box")
            if instruction_box:
                instruction_list = instruction_box.find(["ol", "ul"])
                if instruction_list:
                    recipe["instructions"] = [
                        text
                        for item in instruction_list.find_all("li", recursive=False)
                        if (text := item.get_text(" ", strip=True))
                    ]
                else:
                    recipe["instructions"] = [
                        text
                        for paragraph in instruction_box.find_all("p")
                        if (text := paragraph.get_text(" ", strip=True))
                    ]
            preparation_container = instructions_heading.find_next(
                "div", class_=re.compile(r"print:text-xs")
            )
            if preparation_container:
                print_steps = [
                    step.get_text(" ", strip=True)
                    for step in preparation_container.find_all(
                        "div", class_=re.compile(r"print:mb-2")
                    )
                    if step.get_text(" ", strip=True)
                ]
                if print_steps:
                    recipe["instructions"] = print_steps
            if not recipe["instructions"]:
                for following in instructions_heading.find_all_next(
                    ["h2", "h3", "h4", "ol", "ul", "p"]
                ):
                    if following.name in {"h2", "h3", "h4"}:
                        if int(following.name[1]) <= int(instructions_heading.name[1]):
                            break
                        continue
                    if following.name in {"ol", "ul"}:
                        recipe["instructions"] = [
                            item.get_text(" ", strip=True)
                            for item in following.find_all("li")
                            if item.get_text(" ", strip=True)
                        ]
                    elif following.get_text(" ", strip=True):
                        recipe["instructions"].append(
                            following.get_text(" ", strip=True)
                        )

        for preparation in soup.find_all(
            class_=re.compile(r"\brecipe-preparation\b")
        ):
            steps = [
                text
                for paragraph in preparation.find_all(
                    ["p", "span"], recursive=False
                )
                if (text := paragraph.get_text(" ", strip=True))
            ]
            if steps:
                recipe["instructions"] = steps
                break
            step_list = preparation.find(["ol", "ul"])
            if step_list:
                steps = [
                    text
                    for item in step_list.find_all("li")
                    if (text := item.get_text(" ", strip=True))
                    and not re.match(
                        r"(?:előkészítés|sütés|összesen)\s*:",
                        text,
                        re.I,
                    )
                ]
                if steps:
                    recipe["instructions"] = steps
                    break

        for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5"]):
            if not any(
                label in heading.get_text(" ", strip=True).casefold()
                for label in (
                    "elkészítés", "zubereitung", "anleitung", "instructions",
                    "preparation", "method", "rezeptzubereitung",
                )
            ):
                continue
            for section in heading.parent.find_next_siblings():
                if section.name in {"h2", "h3", "h4", "h5"}:
                    break
                step_list = section.find(["ol", "ul"])
                if step_list:
                    recipe["instructions"] = [
                        item.get_text(" ", strip=True)
                        for item in step_list.find_all("li")
                        if item.get_text(" ", strip=True)
                    ]
                    break
            if recipe["instructions"]:
                break
        if not recipe["instructions"]:
            recipe["instructions"] = [
                (item.get("content") or item.get_text(" ", strip=True)).strip()
                for item in soup.select('[itemprop~="recipeInstructions"]')
                if (
                    item.get("content") or item.get_text(" ", strip=True)
                ).strip()
            ]

        instruction_items = soup.select('[itemprop~="recipeInstructions"]')
        microdata_instructions = [
            text
            for item in instruction_items
            if not item.select_one('[itemprop~="recipeInstructions"]')
            and (
                text := (
                    item.get("content") or item.get_text(" ", strip=True)
                ).strip()
            )
        ]

        # If no title found, try to extract from HTML head
        if not recipe["name"]:
            title_tag = soup.find("title")
            if title_tag:
                # Remove domain from title if present
                title_text = title_tag.get_text(strip=True)
                # Extract just the recipe name
                if "|" in title_text:
                    recipe["name"] = title_text.split("|")[0].strip()
                else:
                    recipe["name"] = title_text

        image_meta = soup.find("meta", property="og:image")
        if image_meta and image_meta.get("content"):
            recipe["image_url"] = image_meta["content"]
        if not recipe.get("image_url"):
            image_item = soup.find(attrs={"itemprop": "image"})
            if image_item:
                recipe["image_url"] = (
                    image_item.get("content")
                    or image_item.get("src")
                    or image_item.get("href")
                )

        servings = soup.find("div", class_=re.compile(r"\brecipe-details\b"))
        if servings:
            for detail in servings.find_all("div", class_=re.compile(r"\brecipe-meta\b")):
                match = re.search(r"(\d+)\s+adag", detail.get_text(" ", strip=True), re.I)
                if match:
                    recipe["servings"] = int(match.group(1))
                    recipe["recipeYield"] = recipe["servings"]
                    break

        if schema_recipe:
            for field in (
                "name",
                "description",
                "ingredients",
                "instructions",
                "image_url",
            ):
                if schema_recipe.get(field):
                    recipe[field] = schema_recipe[field]
        if recipe["name"].endswith("| Street Kitchen"):
            recipe["name"] = recipe["name"].rsplit("|", 1)[0].strip()

        article_ingredients, article_instructions = (
            self._extract_labeled_article_sections(soup)
        )
        if article_ingredients:
            recipe["ingredients"] = article_ingredients
        if article_instructions:
            recipe["instructions"] = article_instructions

        bidista_ingredients, bidista_instructions = (
            self._extract_bidista_article_sections(soup)
        )
        if bidista_ingredients:
            recipe["ingredients"] = bidista_ingredients
        if bidista_instructions:
            recipe["instructions"] = bidista_instructions

        kalci_heading = next(
            (
                heading
                for heading in soup.find_all("h1")
                if unicodedata.normalize(
                    "NFC", heading.get_text(" ", strip=True)
                ).casefold() == "a recept"
            ),
            None,
        )
        if kalci_heading:
            method_container = kalci_heading.find_next_sibling("div")
            if method_container:
                recipe_steps = []
                in_recipe_method = False
                step_pattern = re.compile(
                    r"\b(?:összeönt|elkever|meglangyosít|langyosít|belekever|készít|"
                    r"belemorzsol|beleönt|összegyúr|kidagaszt|keleszt|"
                    r"vág|formáz|pihentet|előmelegít|spriccel|"
                    r"levessz|bekapcsol|megsüt|süt|kivesz|tesz|tessz|"
                    r"nyújt|felcsavar|tálal)\w*",
                    re.I,
                )
                for section in method_container.find_all(
                    "section", recursive=False
                ):
                    if section.find("iframe"):
                        in_recipe_method = True
                        continue
                    section_text = section.get_text(" ", strip=True)
                    if re.match(r"további tipp", section_text, re.I):
                        break
                    if not in_recipe_method:
                        continue
                    paragraphs = section.find_all("p")
                    if not paragraphs:
                        prose = section.select_one(".prose")
                        paragraphs = [prose] if prose else []
                    for paragraph in paragraphs:
                        step = paragraph.get_text(" ", strip=True)
                        if step and step_pattern.search(step):
                            recipe_steps.append(step)
                if recipe_steps:
                    recipe["instructions"] = recipe_steps

        if microdata_instructions:
            recipe["instructions"] = microdata_instructions
        elif recipe["instructions"] and all(
            is_recipe_category_label(step) for step in recipe["instructions"]
        ):
            recipe["instructions"] = []

        return recipe

    @staticmethod
    def _extract_labeled_article_sections(
        soup: BeautifulSoup,
    ) -> Tuple[List[Dict[str, str]], List[str]]:
        selectors = (
            ".recipe-prose",
            ".pcon",
            ".pf-content",
            ".article-right .entry",
            ".post-body.entry-content",
            ".entry-content",
            ".entry",
            ".post-content",
            "section.article",
            "article",
        )
        container = next(
            (soup.select_one(selector) for selector in selectors
             if soup.select_one(selector)),
            None,
        )
        if container is None:
            return [], []

        block_tags = (
            "h1", "h2", "h3", "h4", "h5", "p", "div", "ul", "ol", "li",
            "strong", "b",
        )
        blocks = []
        for element in container.find_all(block_tags):
            if element.find(
                ("h1", "h2", "h3", "h4", "h5", "p", "div", "ul", "ol", "li")
            ):
                continue
            text = unicodedata.normalize(
                "NFC", element.get_text("\n", strip=True)
            )
            if text:
                blocks.append((element.name, text))

        ingredient_pattern = re.compile(
            r"hozz[aá]val[oó]|ingredients?|zutaten", re.I
        )
        instruction_pattern = re.compile(
            r"elk[eé]sz[ií]t|zubereitung|anleitung|instructions?|"
            r"preparation|method|rezeptzubereitung|s[uü]t[eé]se",
            re.I,
        )
        ingredient_group_pattern = re.compile(
            r"^(?:(?:a|az)\s+)?[\w\s-]{0,45}"
            r"(?:hoz|hez|höz|tetej[eé]re|kr[eé]m|alap|spinnel[eé]s)\s*:?$",
            re.I,
        )
        instruction_label_pattern = re.compile(
            r"^(?:elk[eé]sz[ií]t\w*|zubereitung|anleitung|"
            r"instructions?|preparation|method)(?:\s*:|\s*$|\s+)",
            re.I,
        )
        irrelevant_content_pattern = re.compile(
            r"hirdet[eé]s|web[aá]ruh[aá]z|k[oö]nyv|facebook|instagram|"
            r"k[oö]vess|tov[aá]bbi receptek|kapcsol[oó]d[oó]|"
            r"ett[oő]l a hozz[aá]val[oó]t[oó]l|ripost h[ií]rek|"
            r"c[ií]mk[eé]k|fittfaz[eé]k|j[oó] [eé]tv[aá]gyat|"
            r"munkafolyamatok k[eé]pekben|\btipp:|"
            r"szerintem adj neki|p[aá]r [oó]ra h[uű]t[eé]s ut[aá]n|"
            r"b[aá]tran aj[aá]nlom|f[aá]zisfot[oó]|^\s*írta\s*:?\s*$",
            re.I,
        )
        timing_metadata_pattern = re.compile(
            r"^\s*\d+(?:-\d+)?\s*(?:perc|óra|minute|min|hour)\b"
            r"(?:\s*[,;:]|\s+(?:ennek|a|az)\b)|"
            r"\b(?:elkészítési\s+idő|elkészítés\s+ideje|"
            r"előkészítési\s+idő|sütési\s+idő|pihentetési\s+idő)\b",
            re.I,
        )
        serving_note_pattern = re.compile(
            r"^(?:kb\.?\s*)?\d+\s+(?:db\s+)?"
            r"(?:közepes(?:\s+méretű)?\s+)?(?:kifli|csig[aá])|"
            r"^\d+\s+db\s+\d+\s*cm\b|"
            r"^(?:kb\.?\s*)?\d+\s+db\s+süteményünk lesz",
            re.I,
        )
        action_pattern = re.compile(
            r"\b(?:keverj|kever|összekever|összedolgoz|összemelegít|"
            r"lapogat|teszünk|összetör|törj|forral|önt|teríts|kanalazz|tegy|"
            r"helyezz|hűtőbe|hagy|dobj|nyomkod|olvaszd|mehet|dolgozz|"
            r"rottyant|szeletel|fűszere|pihen|forgass|süt|pirít|dagaszt|"
            r"nyújt|formáz|keleszt|simít|reszel|tálal|kenj|szórd|"
            r"belereszel|elrendez|megszór|összeállít|felteker|"
            r"megken|ken|megsüt|összefon)\w*",
            re.I,
        )

        ingredients: List[Dict[str, str]] = []
        instructions: List[str] = []
        state = ""
        ingredient_group_seen = set()

        def append_unique(target: List[str], value: str) -> None:
            cleaned = re.sub(r"\s+", " ", value).strip(" \t\r\n:;")
            if cleaned and cleaned not in target:
                target.append(cleaned)

        def append_ingredient(value: str) -> None:
            cleaned = re.sub(r"\s+", " ", value).strip(" \t\r\n:;")
            if not cleaned or cleaned == "-" or serving_note_pattern.search(cleaned):
                return
            if (
                len(cleaned.split()) <= 2
                and ingredient_group_pattern.fullmatch(cleaned.rstrip(":"))
            ):
                return
            if re.match(r"^(?:-|–|—)?\s*(?:esetleg|vagy)\b", cleaned, re.I):
                if ingredients:
                    ingredients[-1]["original"] += f" {cleaned.lstrip('-–— ')}"
                return
            if cleaned.startswith("(") and ingredients:
                ingredients[-1]["original"] += f" {cleaned}"
                return
            if cleaned not in ingredient_group_seen:
                ingredient_group_seen.add(cleaned)
                ingredients.append({"original": cleaned})

        for tag, text in blocks:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if not lines:
                continue
            label_text = lines[0].strip()
            label_without_colon = label_text.rstrip(":").strip()
            label_tail = ""
            if ":" in label_text:
                label_tail = label_text.split(":", 1)[1].strip()

            is_timing_label = bool(
                re.search(
                    r"(?:elk[eé]sz[ií]t[eé]si\s+id[oő]|"
                    r"elk[eé]sz[ií]t[eé]s\s+ideje|"
                    r"el[oő]k[eé]sz[ií]t[eé]si\s+id[oő]|"
                    r"s[uü]t[eé]si\s+id[oő]|pihentet[eé]si\s+id[oő])",
                    label_text,
                    re.I,
                )
            )
            is_instruction_label = not is_timing_label and (bool(
                tag in {"h1", "h2", "h3", "h4", "h5"}
                and instruction_pattern.search(label_text)
            ) or bool(instruction_label_pattern.match(label_text)))
            if is_instruction_label:
                state = "instructions"
                if label_tail and not timing_metadata_pattern.search(label_tail):
                    append_unique(instructions, label_tail)
                for line in lines[1:]:
                    if not timing_metadata_pattern.search(line):
                        append_unique(instructions, line)
                continue

            is_ingredient_label = bool(
                ingredient_pattern.search(label_text)
                and (
                    tag in {"h1", "h2", "h3", "h4", "h5"}
                    or label_text.endswith(":")
                    or re.match(
                        r"^(?:hozz[aá]val[oó]k?|ingredients?|zutaten)\b",
                        label_text,
                        re.I,
                    )
                )
            )
            is_ingredient_group = bool(
                ingredient_group_pattern.fullmatch(label_without_colon)
                and len(label_without_colon) <= 55
                and label_text.endswith(":")
            )
            if is_ingredient_label or is_ingredient_group:
                state = "ingredients"
                ingredient_group_seen.clear()
                if label_tail:
                    append_ingredient(label_tail)
                for line in lines[1:]:
                    append_ingredient(line)
                continue

            if state == "ingredients":
                if tag in {"h1", "h2", "h3", "h4", "h5"}:
                    state = ""
                    continue
                if timing_metadata_pattern.search(text):
                    state = ""
                    continue
                if irrelevant_content_pattern.search(text):
                    state = ""
                    continue
                is_nassolda = "pf-content" in container.get("class", [])
                if is_nassolda and tag == "p":
                    action_index = next(
                        (
                            index
                            for index, line in enumerate(lines)
                            if action_pattern.search(line)
                        ),
                        None,
                    )
                    if action_index is not None:
                        state = "instructions"
                        for line in lines[action_index:]:
                            append_unique(instructions, line)
                        continue
                for line in lines:
                    cleaned = re.sub(r"\s+", " ", line).strip()
                    if len(cleaned) > 60:
                        state = ""
                        break
                    append_ingredient(cleaned)
            elif state == "instructions":
                if tag in {"h1", "h2", "h3", "h4", "h5"}:
                    state = ""
                    continue
                if irrelevant_content_pattern.search(text):
                    state = ""
                    continue
                if serving_note_pattern.search(text):
                    state = ""
                    continue
                if timing_metadata_pattern.search(text):
                    if (
                        container.name == "section"
                        and "article" in container.get("class", [])
                        and instructions
                    ):
                        instructions[-1] += f" {text}"
                    continue
                if (
                    "pf-content" in container.get("class", [])
                    and tag == "p"
                ):
                    instruction_lines = [
                        line for line in lines if action_pattern.search(line)
                    ]
                    if not instruction_lines:
                        continue
                else:
                    instruction_lines = lines
                for line in instruction_lines:
                    append_unique(instructions, line)

        if "pf-content" in container.get("class", []):
            instructions = []
            core_action_pattern = re.compile(
                r"\b(?:összekever|összemelegít|összedolgoz|belelapogat|"
                r"odanyomkod|összetör|rottyant|felforral|öntjük|teríts|kanalazz|"
                r"tegyük|hagyjuk|keverjük|olvaszt|dobj|mehet|hűtőbe|"
                r"dolgozzunk|törjük|szeleteljük|díszítsük)\w*",
                re.I,
            )
            started = False
            for paragraph in container.find_all("p"):
                lines = [
                    line.strip()
                    for line in paragraph.get_text("\n", strip=True).splitlines()
                    if line.strip()
                ]
                if not lines:
                    continue
                if irrelevant_content_pattern.search(" ".join(lines)):
                    if started:
                        break
                    continue
                action_lines = [
                    line for line in lines if core_action_pattern.search(line)
                ]
                if not started:
                    if not action_lines:
                        continue
                    started = True
                elif not action_lines:
                    break
                for line in action_lines:
                    append_unique(instructions, line)

        if (
            "post-body" in container.get("class", [])
            and "entry-content" in container.get("class", [])
        ):
            post_method_pattern = re.compile(
                r"\b(?:összekever|összemelegít|összedolgoz|"
                r"beletesz|belekever|hozzáad|felfuttat|felmelegít|"
                r"süss|süt|forgat|gyúr|dagaszt|nyújt|felteker|"
                r"reszel|formáz|ken|szór|hagy|adagol|kever|"
                r"pihentet|keleszt|tálal|fűszerez|megfordít|"
                r"összeállít|díszít|elrendez|tölt|helyez|szeletel|"
                r"morzsol|lapogat|meghint|olvaszt|tegy|önt|vág|"
                r"szétválaszt)\w*",
                re.I,
            )
            instructions = []
            post_state = ""
            for line in container.get_text("\n", strip=True).splitlines():
                cleaned = unicodedata.normalize(
                    "NFC", re.sub(r"\s+", " ", line).strip()
                )
                if not cleaned:
                    continue
                if irrelevant_content_pattern.search(cleaned):
                    if post_state == "instructions":
                        break
                    post_state = ""
                    continue
                if instruction_label_pattern.match(cleaned):
                    post_state = "instructions"
                    suffix = cleaned.split(":", 1)[1].strip() if ":" in cleaned else ""
                    if suffix and post_method_pattern.search(suffix):
                        append_unique(instructions, suffix)
                    continue
                if (
                    post_state == "ingredients"
                    and len(cleaned) > 40
                    and post_method_pattern.search(cleaned)
                ):
                    post_state = "instructions"
                    append_unique(instructions, cleaned)
                    continue
                if ingredient_pattern.search(cleaned) or (
                    cleaned.endswith(":")
                    and ingredient_group_pattern.fullmatch(
                        cleaned.rstrip(":").strip()
                    )
                ):
                    post_state = "ingredients"
                    continue
                if (
                    post_state == "instructions"
                    and not serving_note_pattern.search(cleaned)
                    and not timing_metadata_pattern.search(cleaned)
                    and post_method_pattern.search(cleaned)
                ):
                    append_unique(instructions, cleaned)
            post_lines = [
                unicodedata.normalize("NFC", line.strip())
                for line in container.get_text("\n", strip=True).splitlines()
                if line.strip()
            ]
            for index, line in enumerate(post_lines):
                folded_label = (
                    unicodedata.normalize("NFKD", line)
                    .encode("ascii", "ignore")
                    .decode("ascii")
                    .casefold()
                )
                if not folded_label.startswith("elkeszites"):
                    continue
                method_lines = [
                    line.split(":", 1)[1].strip()
                    if ":" in line
                    else ""
                ]
                method_lines.extend(post_lines[index + 1 :])
                method_text = " ".join(
                    part for part in method_lines if part
                )
                if method_text:
                    method_text = re.sub(
                        r"([.!?…]+)(?=\S)", r"\1 ", method_text
                    )
                    instructions = [
                        sentence.strip()
                        for sentence in re.split(
                            r"(?<=[.!?])\s+", method_text
                        )
                        if any(
                            action in (
                                unicodedata.normalize("NFKD", sentence)
                                .encode("ascii", "ignore")
                                .decode("ascii")
                                .casefold()
                            )
                            for action in (
                                "kever", "sut", "tolt", "szetvalaszt",
                                "dagaszt", "nyujt", "formaz", "keleszt",
                            )
                        )
                        and not (
                            unicodedata.normalize("NFKD", sentence)
                            .encode("ascii", "ignore")
                            .decode("ascii")
                            .casefold()
                            .startswith(("ez az adag", "bogre merete", "ma csak"))
                        )
                    ]
                    break

        if container.name == "section" and "article" in container.get("class", []):
            merged_ingredients: List[Dict[str, str]] = []
            for ingredient in ingredients:
                text = ingredient["original"]
                if re.search(
                    r"ett[oő]l a hozz[aá]val[oó]t[oó]l",
                    text,
                    re.I,
                ):
                    continue
                if (
                    merged_ingredients
                    and merged_ingredients[-1]["original"].endswith("sovány")
                    and text.casefold() == "túró"
                ):
                    merged_ingredients[-1]["original"] += f" {text}"
                else:
                    merged_ingredients.append(ingredient)
            ingredients = merged_ingredients

            merged_instructions: List[str] = []
            pending_article = ""
            for instruction in instructions:
                if instruction.casefold() in {"a", "az"}:
                    pending_article = instruction
                    continue
                if pending_article:
                    instruction = f"{pending_article} {instruction}"
                    pending_article = ""
                if instruction.casefold().startswith("és ") and merged_instructions:
                    merged_instructions[-1] += f" {instruction}"
                    continue
                merged_instructions.append(instruction)
            if pending_article:
                merged_instructions.append(pending_article)
            instructions = merged_instructions
        if container.name == "article":
            instructions = [
                re.sub(
                    r"\s+j\s+étvágyat!?\s*$",
                    "",
                    instruction,
                    flags=re.I,
                )
                for instruction in instructions
            ]

        return ingredients, instructions

    @staticmethod
    def _extract_bidista_article_sections(
        soup: BeautifulSoup,
    ) -> Tuple[List[Dict[str, str]], List[str]]:
        canonical = soup.find("link", rel="canonical")
        canonical_url = canonical.get("href", "") if canonical else ""
        if not re.match(r"https?://(?:www\.)?bidista\.com(?:/|$)", canonical_url, re.I):
            return [], []

        container = soup.select_one("article .td-post-content")
        if container is None:
            return [], []

        ingredients: List[Dict[str, str]] = []
        instructions: List[str] = []
        state = ""
        heading_tags = {"h1", "h2", "h3", "h4", "h5"}
        ingredient_label = re.compile(r"hozz[aá]val[oó]k?", re.I)
        instruction_label = re.compile(r"elk[eé]sz[ií]t", re.I)

        for element in container.find_all(recursive=False):
            if not element.name or element.name in {"script", "style"}:
                continue

            text = re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()
            if element.name in heading_tags:
                if instruction_label.search(text):
                    state = "instructions"
                elif state == "ingredients" or ingredient_label.search(text):
                    state = "ingredients"
                elif state == "instructions":
                    break
                continue

            if state == "ingredients":
                if element.name in {"ul", "ol"}:
                    ingredients.extend(
                        {"original": item_text}
                        for item in element.find_all("li", recursive=False)
                        if (item_text := item.get_text(" ", strip=True))
                    )
                continue

            if state == "instructions":
                if element.find("a", href=True):
                    break
                text = re.sub(
                    r"\s+j(?:ó)?\s+étvágyat!?\s*$",
                    "",
                    text,
                    flags=re.I,
                ).strip()
                if re.fullmatch(r"j(?:ó)?\s+étvágyat!?", text, re.I):
                    continue
                if element.name in {"p", "li"} and text and text not in instructions:
                    instructions.append(text)
                elif element.name in {"ul", "ol"}:
                    instructions.extend(
                        item_text
                        for item in element.find_all("li", recursive=False)
                        if (item_text := item.get_text(" ", strip=True))
                        and item_text not in instructions
                    )

        return ingredients, instructions

    @staticmethod
    def _extract_jsonld_recipe(soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        def find_recipes(value: Any):
            if isinstance(value, list):
                for item in value:
                    yield from find_recipes(item)
            elif isinstance(value, dict):
                types = value.get("@type", [])
                if isinstance(types, str):
                    types = [types]
                if any(
                    str(item).rsplit("/", 1)[-1].casefold() == "recipe"
                    for item in types
                ):
                    yield value
                for key in ("@graph", "mainEntity", "mainEntityOfPage"):
                    if key in value:
                        yield from find_recipes(value[key])

        def text(value: Any) -> str:
            if isinstance(value, str):
                return re.sub(r"\s+", " ", value).strip()
            if isinstance(value, dict):
                return text(value.get("text") or value.get("name") or "")
            return ""

        def instruction_steps(value: Any) -> List[str]:
            if isinstance(value, str):
                return [text(value)] if text(value) else []
            if isinstance(value, list):
                return [step for item in value for step in instruction_steps(item)]
            if isinstance(value, dict):
                if value.get("text"):
                    return [text(value["text"])]
                return instruction_steps(value.get("itemListElement", []))
            return []

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or script.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            for item in find_recipes(data):
                ingredients = item.get("recipeIngredient", [])
                if isinstance(ingredients, str):
                    ingredients = [ingredients]
                if not isinstance(ingredients, list):
                    ingredients = []

                images = item.get("image", [])
                if not isinstance(images, list):
                    images = [images]
                image_url = next(
                    (
                        candidate
                        for image in images
                        if (
                            candidate := text(
                                image.get("url") or image.get("contentUrl")
                                if isinstance(image, dict)
                                else image
                            )
                        )
                        and not re.search(
                            r"(?:^|[/_.-])logo(?:[./?_-]|$)",
                            candidate,
                            re.I,
                        )
                    ),
                    "",
                )

                servings = item.get("recipeYield", 1)
                servings_text = text(servings)
                serving_match = re.search(r"\d+", servings_text)
                servings_count = int(serving_match.group()) if serving_match else 1
                category = item.get("recipeCategory", [])
                instructions = instruction_steps(
                    item.get("recipeInstructions", [])
                )
                if instructions and all(
                    is_recipe_category_label(step) for step in instructions
                ):
                    instructions = []
                return {
                    "name": text(item.get("name")),
                    "description": text(item.get("description")),
                    "ingredients": [
                        {"original": text(ingredient)}
                        for ingredient in ingredients
                        if text(ingredient)
                    ],
                    "instructions": instructions,
                    "servings": servings_count,
                    "recipeYield": servings_text or servings_count,
                    "tags": category if isinstance(category, list) else [category] if category else [],
                    "image_url": image_url,
                }
        return None

    def scrape_recipe_from_url(self, url: str) -> Dict[str, Any]:
        """
        Scrape recipe data from a web page.
        """
        print(f"Scraping recipe from {url}...")
        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                )
            },
            timeout=30,
        )
        response.raise_for_status()
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.content, "html.parser")

        recipe = self._extract_recipe_from_html(soup)
        recipe["orgURL"] = response.url
        recipe["source_url"] = response.url
        if recipe.get("image_url"):
            recipe["image_url"] = urljoin(response.url, recipe["image_url"])

        return recipe

    @staticmethod
    def _slugify(name: str) -> str:
        normalized = unicodedata.normalize("NFKD", name)
        ascii_name = normalized.encode("ascii", "ignore").decode("ascii").lower()
        return re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")

    def _find_existing_recipe(self, name: str) -> Optional[str]:
        response = self.session.get(
            f"{self.base_url}/api/recipes",
            params={"search": name, "perPage": 100},
            timeout=30,
        )
        response.raise_for_status()
        target_slug = self._slugify(name)
        target_name = " ".join(name.casefold().split())
        for existing in response.json().get("items", []):
            slug = existing.get("slug")
            existing_name = existing.get("name")
            if slug == target_slug or (
                isinstance(existing_name, str)
                and " ".join(existing_name.casefold().split()) == target_name
            ):
                return slug
        return None

    def upload_recipe(self, recipe: Dict[str, Any]) -> Optional[str]:
        """Create or update a complete recipe in Mealie and return its slug."""
        if not recipe.get("name"):
            raise ValueError("Recipe must have a name")

        instructions = recipe.get("instructions", [])
        if isinstance(instructions, str):
            instructions = [instructions] if instructions.strip() else []
        recipe_data = {
            "name": recipe["name"],
            "description": recipe.get("description", ""),
            "recipeIngredient": [
                {"note": text, "originalText": text}
                for ingredient in recipe.get("ingredients", [])
                if (
                    text := (
                        ingredient.get("original", "")
                        if isinstance(ingredient, dict)
                        else str(ingredient)
                    ).strip()
                )
            ],
            "recipeInstructions": [
                {"text": step} for step in instructions if step.strip()
            ],
            "recipeServings": recipe.get("servings", 0),
            "recipeYield": str(recipe.get("recipeYield", recipe.get("servings", ""))),
            "orgURL": recipe.get("orgURL"),
        }

        try:
            recipe_slug = self._find_existing_recipe(recipe["name"])
            if recipe_slug:
                response = self.session.patch(
                    f"{self.base_url}/api/recipes/{recipe_slug}",
                    json=recipe_data,
                    timeout=30,
                )
            else:
                response = self.session.post(
                    f"{self.base_url}/api/recipes",
                    json={"name": recipe["name"]},
                    timeout=30,
                )
                response.raise_for_status()
                recipe_slug = response.json()
                response = self.session.patch(
                    f"{self.base_url}/api/recipes/{recipe_slug}",
                    json=recipe_data,
                    timeout=30,
                )
            response.raise_for_status()

            stored = self.session.get(
                f"{self.base_url}/api/recipes/{recipe_slug}",
                timeout=30,
            )
            stored.raise_for_status()
            stored_recipe = stored.json()
            stored_ingredients = stored_recipe.get("recipeIngredient", [])
            expected_ingredients = recipe_data["recipeIngredient"]
            if (
                len(stored_ingredients) != len(expected_ingredients)
                or any(
                    saved.get("display") != expected["note"]
                    for saved, expected in zip(stored_ingredients, expected_ingredients)
                )
                or len(stored_recipe.get("recipeInstructions", []))
                != len(recipe_data["recipeInstructions"])
                or any(
                    saved.get("text") != expected["text"]
                    for saved, expected in zip(
                        stored_recipe.get("recipeInstructions", []),
                        recipe_data["recipeInstructions"],
                    )
                )
            ):
                raise RuntimeError(
                    f"Mealie did not save all ingredient display text and instruction text for {recipe_slug}"
                )

            print(
                f"[+] Verified {len(recipe_data['recipeIngredient'])} ingredients "
                f"and {len(recipe_data['recipeInstructions'])} steps "
                f"(slug: {recipe_slug})"
            )
            if recipe.get("image_url"):
                self._upload_recipe_image(recipe_slug, recipe["image_url"])
            return recipe_slug
        except requests.exceptions.RequestException as e:
            print(f"[-] Error uploading recipe: {e}")
            if e.response is not None:
                print(f"    Response: {e.response.text}")
            raise RuntimeError(f"Mealie API request failed: {e}") from e

    def import_bookmarks(
        self, filepath: str, report_path: Optional[str] = None
    ) -> Dict[str, int]:
        bookmarks = parse_bookmark_folder(filepath, "Receptek")
        if report_path:
            report_file = Path(report_path).expanduser()
            if not report_file.is_absolute():
                report_file = Path.cwd() / report_file
        else:
            source_file = Path(filepath).expanduser().resolve()
            report_file = source_file.with_name(f"{source_file.stem}_import_report.csv")
        report_file.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "title",
            "url",
            "final_url",
            "status",
            "recipe_slug",
            "ingredient_count",
            "instruction_count",
            "error",
        ]

        def save_report(rows):
            with report_file.open("w", newline="", encoding="utf-8-sig") as report:
                writer = csv.DictWriter(report, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

        try:
            response = self.session.get(
                f"{self.base_url}/api/recipes",
                params={"perPage": 1},
                timeout=30,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as error:
            blocked_results = [
                {
                    "title": bookmark["title"],
                    "url": bookmark["url"],
                    "final_url": "",
                    "status": "blocked",
                    "recipe_slug": "",
                    "ingredient_count": 0,
                    "instruction_count": 0,
                    "error": f"Mealie authorization preflight failed: {error}",
                }
                for bookmark in bookmarks
            ]
            save_report(blocked_results)
            print(
                f"Bookmark import blocked: Mealie API access failed; "
                f"{len(blocked_results)} URLs recorded."
            )
            print(f"Detailed report: {report_file}")
            return {
                "total": len(blocked_results),
                "verified": 0,
                "failed": 0,
                "blocked": len(blocked_results),
            }

        results = []
        for index, bookmark in enumerate(bookmarks, start=1):
            result = {
                "title": bookmark["title"],
                "url": bookmark["url"],
                "final_url": "",
                "status": "failed",
                "recipe_slug": "",
                "ingredient_count": 0,
                "instruction_count": 0,
                "error": "",
            }
            print(f"[{index}/{len(bookmarks)}] {bookmark['title']}: {bookmark['url']}")
            try:
                recipe = self.scrape_recipe_from_url(bookmark["url"])
                result["final_url"] = recipe.get("source_url", "")
                result["ingredient_count"] = len(recipe.get("ingredients", []))
                instructions = recipe.get("instructions", [])
                result["instruction_count"] = (
                    len(instructions) if isinstance(instructions, list)
                    else int(bool(instructions))
                )
                if not recipe.get("name"):
                    raise ValueError("Page did not contain a recipe title")
                if not recipe.get("ingredients"):
                    raise ValueError("Page did not contain recipe ingredients")
                if not instructions:
                    raise ValueError("Page did not contain recipe instructions")
                result["recipe_slug"] = self.upload_recipe(recipe) or ""
                result["status"] = "verified"
            except Exception as error:
                result["error"] = f"{type(error).__name__}: {error}"
                print(f"[-] {result['error']}")
            results.append(result)
            save_report(results)
            print()

        summary = {
            "total": len(results),
            "verified": sum(result["status"] == "verified" for result in results),
            "failed": sum(result["status"] == "failed" for result in results),
            "blocked": 0,
        }
        print(
            f"Bookmark import finished: {summary['verified']} verified, "
            f"{summary['failed']} failed, {summary['total']} total."
        )
        print(f"Detailed report: {report_file}")
        return summary

    def _upload_recipe_image(self, recipe_id: str, image_url: str):
        """
        Download and upload image for a recipe
        """
        try:
            print(f"  [*] Downloading image from {image_url}...")
            img_response = requests.get(image_url, timeout=10)
            img_response.raise_for_status()
            
            # Determine image format
            content_type = img_response.headers.get("content-type", "image/jpeg")
            ext = mimetypes.guess_extension(content_type) or ".jpg"
            
            # Upload image to Mealie
            files = {
                "image": (f"recipe_image{ext}", img_response.content, content_type)
            }
            
            response = self.session.put(
                f"{self.base_url}/api/recipes/{recipe_id}/image",
                files=files,
                data={"extension": ext.lstrip(".")},
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=30
            )
            response.raise_for_status()
            print(f"  [+] Image uploaded successfully")
        except Exception as e:
            print(f"  [!] Warning: Could not upload image: {e}")

    def find_recipes_on_site(self, base_url: str = "https://www.mindmegette.hu", limit: int = 5) -> List[str]:
        """
        Find recipe URLs on mindmegette.hu
        """
        print(f"Searching for recipes on {base_url}...")
        recipes = []
        
        try:
            # Try to get the recipe listing page
            response = requests.get(f"{base_url}/receptek")
            soup = BeautifulSoup(response.content, "html.parser")
            
            # Find recipe links
            for link in soup.find_all("a"):
                href = link.get("href")
                if href and "/recept/" in href:
                    if not href.startswith("http"):
                        href = urljoin(base_url, href)
                    recipes.append(href)
                    if len(recipes) >= limit:
                        break
        except Exception as e:
            print(f"Warning: Could not fetch recipe list: {e}")
        
        return recipes[:limit]


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Import recipes from supported websites into Mealie."
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="Import only the recipe at this URL instead of running the default batch",
    )
    parser.add_argument(
        "--bookmarks",
        help='Import every link in the "Receptek" folder and its subfolders from a Netscape bookmark HTML file',
    )
    parser.add_argument(
        "--report",
        help="Write bookmark import results to this CSV path (defaults beside the bookmark file)",
    )
    args = parser.parse_args()

    if args.url and args.bookmarks:
        parser.error("a URL and --bookmarks cannot be used together")
    if args.report and not args.bookmarks:
        parser.error("--report requires --bookmarks")

    importer = MealieRecipeImporter()

    if args.bookmarks:
        summary = importer.import_bookmarks(args.bookmarks, args.report)
        if summary["failed"] or summary.get("blocked"):
            raise SystemExit(1)
        return

    if args.url:
        recipe = importer.scrape_recipe_from_url(args.url)
        recipe_id = importer.upload_recipe(recipe)
        if not recipe_id:
            raise SystemExit("Recipe import failed; see the error above.")
        print(f"[+] Recipe imported successfully (slug: {recipe_id})")
        return
    
    # Task 1: Import from MHTML file
    print("=" * 60)
    print("TASK 1: Importing from MHTML file")
    print("=" * 60)
    
    if MHTML_FILE:
        mhtml_file = Path(MHTML_FILE).expanduser()
        if not mhtml_file.is_absolute():
            mhtml_file = PROJECT_DIR / mhtml_file
    else:
        mhtml_file = None

    if mhtml_file and mhtml_file.exists():
        try:
            recipe = importer.parse_mhtml_file(str(mhtml_file))
            print(f"\nExtracted recipe: {recipe['name']}")
            print(f"Ingredients: {len(recipe['ingredients'])}")
            print(f"Instructions: {len(recipe['instructions'])} steps")
            
            recipe_id = importer.upload_recipe(recipe)
            if recipe_id:
                print(f"[+] Recipe imported successfully!\n")
        except Exception as e:
            print(f"[-] Error processing MHTML file: {e}\n")
    elif mhtml_file:
        print("Configured MHTML_FILE does not exist; skipping MHTML import.\n")
    else:
        print("No MHTML_FILE configured; skipping MHTML import.\n")

    # Task 2: Scrape and import from website
    print("=" * 60)
    print("TASK 2: Scraping recipes from mindmegette.hu")
    print("=" * 60)
    
    recipe_urls = RECIPE_URLS.copy()
    
    # Optionally, find more recipes
    try:
        additional_urls = importer.find_recipes_on_site(limit=3)
        recipe_urls.extend(url for url in additional_urls if url not in recipe_urls)
    except Exception as e:
        print(f"Warning: Could not find additional recipes: {e}")
    
    print(f"\nFound {len(recipe_urls)} recipe(s) to import:\n")
    
    for url in recipe_urls[:5]:  # Limit to first 5 recipes
        try:
            recipe = importer.scrape_recipe_from_url(url)
            recipe_id = importer.upload_recipe(recipe)
            print()
        except Exception as e:
            print(f"[-] Error processing {url}: {e}\n")


if __name__ == "__main__":
    main()
