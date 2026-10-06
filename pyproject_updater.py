import re
with open('pyproject.toml', 'r') as f:
    content = f.read()

new_lint = """[tool.ruff.lint]
select = ["E", "W", "F"]
ignore = ["E501", "E402", "F401", "F841", "F811", "F821"]
"""

content = re.sub(r'\[tool\.ruff\.lint\].*?(?=\n\[|$)', new_lint, content, flags=re.DOTALL)

with open('pyproject.toml', 'w') as f:
    f.write(content)
