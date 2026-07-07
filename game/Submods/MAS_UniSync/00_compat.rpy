python early:
    import sys
    import types

    if b"renpy.revertable" not in sys.modules:
        renpy_python = sys.modules.get(b"renpy.python")
        revertable_module = types.ModuleType(b"renpy.revertable")

        if renpy_python is not None:
            revertable_module.RevertableDict = renpy_python.RevertableDict
            revertable_module.RevertableList = renpy_python.RevertableList
            revertable_module.RevertableSet = renpy_python.RevertableSet

        else:
            class RevertableList(list):
                pass

            class RevertableDict(dict):
                pass

            class RevertableSet(set):
                pass

            revertable_module.RevertableDict = RevertableDict
            revertable_module.RevertableList = RevertableList
            revertable_module.RevertableSet = RevertableSet

        sys.modules[b"renpy.revertable"] = revertable_module
