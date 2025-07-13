import json
from bs4 import BeautifulSoup
from tqdm import tqdm

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
            readings.append(process_b_tag(element))
        elif element.name != "br":  # Stop at first non-br element
            break

    # Remove initial b/br elements
    for element in soup.find_all(recursive=False):
        if element.name in ["b", "br"]:
            element.decompose()
        else:
            break

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


def convert_to_yomitan(input_lines):
    """Convert Lingvo Ru-En dictionary to Yomitan JSON format"""
    entries = []
    non_empty_lines = [line for line in input_lines if line.strip()]
    sequence = 0

    for line in tqdm(non_empty_lines, desc="Processing entries", unit="entry"):
        # Find the position of the first "<" to separate headword and HTML
        first_lt = line.find("<")
        if first_lt == -1:
            continue  # Skip if no HTML found

        headword_str = line[:first_lt].strip()
        html_str = line[first_lt:].strip()

        # Split multiple headwords separated by pipes
        headwords = [h.strip() for h in headword_str.split("|")]

        # Process HTML and extract readings
        cleaned_html, readings_list = clean_html_and_extract_readings(html_str)
        structured_content = convert_html_to_content(cleaned_html)

        # Create entries for each headword
        for headword in headwords:
            # Determine reading: phrases keep original, words use extracted reading
            if " " in headword:
                reading = headword
            elif readings_list:
                reading = readings_list.pop(0)
            else:
                reading = headword

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
            entries.append(entry)
            sequence += 1

    return entries


# Example usage
if __name__ == "__main__":
    with open("LingvoUniversalRuEn.txt", "r", encoding="utf-8") as f:
        input_lines = f.readlines()

    yomitan_data = convert_to_yomitan(input_lines)

    with open("term_bank_1.json", "w", encoding="utf-8") as f:
        json.dump(yomitan_data, f, ensure_ascii=False, indent=2)
