import json
from bs4 import BeautifulSoup
from tqdm import tqdm
import re

ACCENT_MAP = {
    "а": "а́",
    "е": "е́",
    "и": "и́",
    "о": "о́",
    "у": "у́",
    "ы": "ы́",
    "э": "э́",
    "ю": "ю́",
    "я": "я́",
    "А": "А́",
    "Е": "Е́",
    "И": "И́",
    "О": "О́",
    "У": "У́",
    "Ы": "Ы́",
    "Э": "Э́",
    "Ю": "Ю́",
    "Я": "Я́",
}


def has_accented_vowels(text):
    """Check if text contains any stress markers (acute accents or ё)"""
    return any(accent in text for accent in ACCENT_MAP.values()) or "ё" in text.lower()


def should_use_reading(text, reading_candidate):
    """Determine whether to use the reading candidate"""
    # Count the number of vowels in the headword
    vowels_in_headword = sum(1 for char in text if char.lower() in "аеёиоуыэюя")

    # Rule 1: Always empty if no acute vowels
    if not has_accented_vowels(reading_candidate):
        return False

    # Rule 2: Empty if headword has only one vowel (stress is unambiguous)
    if vowels_in_headword <= 1:
        return False

    return True


def process_b_tag(b_tag):
    """Extract text from <b> tag and replace accented vowels"""
    text = ""
    for child in b_tag.children:
        if isinstance(child, str):
            text += child
        elif child.name == "u" and "accent" in child.get("class", []):
            vowel = child.string
            if vowel in ACCENT_MAP:
                text += ACCENT_MAP[vowel]
            else:
                text += vowel
        else:
            # For any other element, get its text content
            text += child.get_text()
    return text


def clean_html_and_extract_readings(html_str):
    """Remove audio tags and extract readings from initial <b> tags"""
    soup = BeautifulSoup(html_str, "html.parser")

    # Remove all audio tags
    for obj in soup.find_all("object"):
        obj.decompose()

    # Extract readings from top-level <b> tags
    readings = []
    for element in soup.find_all(recursive=False):
        if element.name == "b":
            content = element.get_text().strip()
            if len(content) == 1 and content in "IVX":
                break
            has_accent = bool(element.find("u", class_="accent"))
            if not has_accent:
                break
            readings.append(process_b_tag(element))
        elif element.name != "br":  # Stop at first non-br element
            break

    if not readings:
        # Get the first top-level block (e.g., <p>, <div>, etc.)
        first_block = next(
            (
                child
                for child in soup.children
                if child.name not in [None, "object", "br"]
            ),
            None,
        )

        # Check if the first block is a <font> tag with color="green"
        if (
            first_block
            and first_block.name == "font"
            and first_block.get("color", "").lower() == "green"
        ):
            text = first_block.get_text().strip()
            if text.startswith("(") and text.endswith(")"):
                first_paren = text[text.find("(") + 1 : text.find(")")].strip()
                if "ё" in first_paren:
                    if "/" in first_paren:
                        for reading in first_paren.split("/"):
                            readings.append(reading)
                    else:
                        readings.append(first_paren)

    # Remove initial b/br elements
    # for element in soup.find_all(recursive=False):
    #     if element.name in ["b", "br"]:
    #         content = element.get_text().strip()
    #         if len(content) == 1 and content in "IVX":
    #             break
    #         element.decompose()
    #     else:
    #         break

    return str(soup), readings


def convert_style(style_str):
    """Convert HTML style to Yomitan style object"""
    if not style_str:
        return {}

    styles = {}
    for prop in style_str.split(";"):
        prop = prop.strip()
        if ":" not in prop:
            continue
        key, value = [p.strip() for p in prop.split(":", 1)]

        if key == "color":
            styles["color"] = value
        elif key == "margin-left":
            styles["marginLeft"] = value
        elif key == "padding-left":
            styles["paddingLeft"] = value
        elif key == "margin":
            styles["margin"] = value
        elif key == "padding":
            styles["padding"] = value
        elif key == "font-style" and value == "italic":
            styles["fontStyle"] = "italic"
        elif key == "font-weight" and value == "bold":
            styles["fontWeight"] = "bold"
        elif key == "text-decoration" and value == "underline":
            styles["textDecorationLine"] = "underline"

    return styles


def convert_html_to_content(html_str):
    """Convert HTML fragment to Yomitan structured content"""
    soup = BeautifulSoup(f"<div>{html_str}</div>", "html.parser")
    root = soup.div

    def process_node(node):
        if node.name is None:  # Text node
            return str(node)

        # Handle <br> tags as line breaks
        if node.name == "br":
            return {"tag": "br"}

        # Convert font tags to spans and handle color attribute
        if node.name == "font":
            color = node.get("color")
            if color:
                # Create a span with color style
                span = soup.new_tag("span")
                span["style"] = f"color: {color};"
                # Move children to new span
                for child in node.contents:
                    span.append(child)
                node.replace_with(span)
                # Reprocess the new node
                return process_node(span)
            else:
                # Treat as regular span
                node.name = "span"

        # Handle different element types
        if node.name in ["div", "span"]:
            tag = node.name
        elif node.name == "a" and node.get("href"):
            tag = "a"
        elif node.name == "p":
            tag = "div"
        else:
            tag = "span"

        # Process children
        content = []
        for child in node.children:
            processed = process_node(child)
            if processed:
                content.append(processed)

        # Handle empty content
        if not content:
            content = [""]

        # Create node object
        node_obj = {"tag": tag, "content": content}

        # Special handling for links
        if node.name == "a" and node.get("href"):
            href = node["href"]
            if href.startswith("bword://"):
                href = href.replace(
                    "bword://", "", 1
                )  # The 1 ensures only the first occurrence is replaced
            if not href.startswith(("http:", "https:", "?")):
                href = f"?query={href}&wildcards=off"
            node_obj["href"] = href

        # Add styling
        style = convert_style(node.get("style", ""))
        if style:
            node_obj["style"] = style

        # Handle semantic tags
        if node.name == "i" and "fontStyle" not in node_obj.get("style", {}):
            node_obj.setdefault("style", {})["fontStyle"] = "italic"
        if node.name == "b" and "fontWeight" not in node_obj.get("style", {}):
            node_obj.setdefault("style", {})["fontWeight"] = "bold"
        if node.name == "u" and "textDecorationLine" not in node_obj.get("style", {}):
            node_obj.setdefault("style", {})["textDecorationLine"] = "underline"

        # Handle class attribute
        if node.get("class"):
            node_obj.setdefault("data", {})["class"] = " ".join(node["class"])

        return node_obj

    return process_node(root)


# Normalize both strings for comparison
def normalize(s):
    return (
        s.replace("ё", "е")
        .replace("\u0301", "")
        .replace("-", "")
        .replace(" ", "")
        .lower()
    )


def convert_to_yomitan(input_lines, debug):
    """Convert Lingvo Ru-En dictionary to Yomitan JSON format"""
    entries = []
    non_empty_lines = [line for line in input_lines if line.strip()]
    sequence = 0
    reading_or_link_num = 0
    phrases_num = 0

    for line in tqdm(non_empty_lines, desc="Processing entries", unit="entry"):
        line_copy = line
        # Find the position of the first "<" to separate headword and HTML
        first_lt = line.find("<")
        if first_lt == -1:
            continue  # Skip if no HTML found

        # Hardcoded exception as revision
        exceptions = ["незарифленный", "обдернуться", "обмерзать"]

        headword_str = line[:first_lt].strip()
        html_str = line[first_lt:].strip()

        if headword_str in exceptions:
            continue

        # Split multiple headwords separated by pipes
        headwords = [h.strip() for h in headword_str.split("|")]

        # Process HTML and extract readings
        cleaned_html, readings_list = clean_html_and_extract_readings(html_str)
        structured_content = convert_html_to_content(cleaned_html)

        is_phrase = False

        for headword in headwords:
            if " " in headword:
                is_phrase = True
                break

        if not is_phrase:
            if not readings_list and "bword" in cleaned_html:
                reading_or_link_num += 1
            else:
                reading_or_link_num += len(readings_list)

        # Create entries for each headword
        for headword in headwords:
            # Determine reading: phrases keep original, words use extracted reading
            # Sometimes phrase has reading: Али Баба
            if " " in headword:
                phrases_num += 1
            reading = ""
            if readings_list:
                reading_candidate = readings_list[0]
                if "(" in reading_candidate and ")" in reading_candidate:
                    # Variant 1: With parenthetical content (remove parentheses but keep content)
                    variant1 = re.sub(r"\(([^)]*)\)", r"\1", reading_candidate)

                    # Variant 2: Without parenthetical content (remove parentheses and their content)
                    variant2 = re.sub(r"\([^)]*\)", "", reading_candidate)

                    # Clean up whitespace and return non-empty variants
                    variants = [" ".join(variant1.split()), " ".join(variant2.split())]

                    for variant in variants:
                        norm_reading = normalize(variant)
                        norm_headword = normalize(headword)

                        if norm_reading == norm_headword:
                            _ = readings_list.pop(0)
                            reading = (
                                variant
                                if should_use_reading(headword, variant)
                                else headword
                            )
                else:
                    norm_reading = normalize(reading_candidate)
                    norm_headword = normalize(headword)
                    reading_space_num = reading_candidate.count(" ")
                    headword_space_num = headword.count(" ")
                    if (
                        norm_reading != norm_headword
                        or reading_space_num != headword_space_num
                    ):
                        reading = headword
                    else:
                        reading_candidate = readings_list.pop(0)
                        reading = (
                            reading_candidate
                            if should_use_reading(headword, reading_candidate)
                            else headword
                        )
            else:
                reading = headword

            try:
                reading_space_num = reading.count(" ")
                headword_space_num = headword.count(" ")

                if reading_space_num != headword_space_num:
                    raise ValueError(
                        "Word Num Not Match!\n"
                        f"Reading validation failed: '{reading}'"
                        f"doesn't match headword '{headword}'\n"
                    )

                reading_words = reading.split(" ")
                headword_words = headword.split(" ")

                for i in range(len(reading_words)):
                    if "ё" in reading_words[i]:
                        headword_words[i] = reading_words[i]

                headword = " ".join(headword_words)

                norm_reading = normalize(reading)
                norm_headword = normalize(headword)
                reading_space_num = reading.count(" ")
                headword_space_num = headword.count(" ")

                if (
                    norm_reading != norm_headword
                    or reading_space_num != headword_space_num
                ):
                    raise ValueError(
                        f"Reading validation failed: '{reading}'"
                        f"doesn't match headword '{headword}'\n"
                        f"norm_reading '{norm_reading}'\n"
                        f"norm_headword '{norm_headword}'"
                    )

                # Build Yomitan entry with proper schema compliance
                entry = [
                    headword,  # Term
                    reading,  # Reading
                    "",  # Definition tags
                    "",  # Rules
                    0,  # Score
                    [{"type": "structured-content", "content": structured_content}],
                    sequence,  # Sequence
                    "",  # Term tags
                ]

            except ValueError as e:
                # Write the line_copy to test.txt when ValueError is raised
                if debug:
                    with open("test.txt", "a", encoding="utf-8") as f:
                        f.write(line_copy)
                # Re-raise the exception if you want to stop execution or handle it elsewhere
                raise e

            entries.append(entry)
            sequence += 1

        if readings_list:
            if debug:
                with open("test.txt", "a", encoding="utf-8") as f:
                    f.write(line_copy)

            for reading in readings_list:
                print(reading)

            raise ValueError("Readings not used up!")

    return entries, reading_or_link_num, phrases_num


# Example usage
if __name__ == "__main__":
    with open("test.txt", "r", encoding="utf-8") as f:
        test_lines = f.readlines()

    test_data, readings_num, phrases_num = convert_to_yomitan(test_lines, debug=False)

    print(readings_num, phrases_num)

    with open("LingvoUniversalRuEn.txt", "r", encoding="utf-8") as f:
        input_lines = f.readlines()

    yomitan_data, readings_num, phrases_num = convert_to_yomitan(
        input_lines, debug=True
    )

    print(readings_num, phrases_num)

    with open("term_bank_1.json", "w", encoding="utf-8") as f:
        json.dump(yomitan_data, f, ensure_ascii=False, indent=2)
