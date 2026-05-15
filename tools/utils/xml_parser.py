"""Helper de parseo XML compartido.
Extrae texto de un elemento XML devolviendo cadena vacía si no existe.
"""
import xml.etree.ElementTree as ET


def _text(element: ET.Element, tag: str) -> str:
    """Devuelve el texto de un subelemento o cadena vacía si no existe."""
    node = element.find(tag)
    if node is None or not node.text:
        return ""
    return node.text.strip()
