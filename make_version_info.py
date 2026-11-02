"""Writes version_info.txt for PyInstaller (--version-file), so PointLoose.exe shows
its name, version and copyright under Properties > Details."""
from pointloose_version import APP_NAME, COPYRIGHT, DESCRIPTION, VERSION

nums = tuple(int(x) for x in VERSION.split(".")) + (0,)
TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'The {name} Authors'),
      StringStruct('FileDescription', '{desc}'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', '{name}'),
      StringStruct('LegalCopyright', '{copy}'),
      StringStruct('OriginalFilename', '{name}.exe'),
      StringStruct('ProductName', '{name}'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

with open("version_info.txt", "w", encoding="utf-8") as f:
    f.write(TEMPLATE.format(nums=nums, name=APP_NAME, desc=DESCRIPTION, ver=VERSION, copy=COPYRIGHT))
print("version_info.txt written for %s %s" % (APP_NAME, VERSION))
