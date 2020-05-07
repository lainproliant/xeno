# --------------------------------------------------------------------
# namespace.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday May 7, 2020
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------


# --------------------------------------------------------------------
class Namespace:
    ROOT = "@root"
    SEP = "/"

    @staticmethod
    def join(*args):
        return Namespace.SEP.join(args)

    @staticmethod
    def root():
        return Namespace(Namespace.ROOT)

    @staticmethod
    def leaf_name(name):
        return name.split(Namespace.SEP)[-1]

    def __init__(self, name):
        self.name = name
        self.sub_namespaces = {}
        self.leaves = set()

    def add(self, name):
        if not name:
            raise ValueError("Leaf node name is empty!")
        parts = name.split(Namespace.SEP)
        if len(parts) == 1:
            if name in self.sub_namespaces:
                raise ValueError(
                    'Leaf node cannot have the same name as an existing '
                    'namespace: "%s"'
                    % name
                )
            self.leaves.add(name)
        else:
            if not parts[0] in self.sub_namespaces:
                if parts[0] in self.leaves:
                    raise ValueError(
                        'Namespace cannot have the same name as an existing '
                        'leaf node: "%s"'
                        % parts[0]
                    )
                self.sub_namespaces[parts[0]] = Namespace(parts[0])
            namespace = self.sub_namespaces[parts[0]]
            namespace.add(Namespace.join(*parts[1:]))

    def add_namespace(self, name):
        if not name:
            raise ValueError("Namespace name is empty!")
        parts = name.split(Namespace.SEP)
        ns = self
        for part in parts:
            if part in ns.sub_namespaces:
                ns = ns.sub_namespaces[part]
            else:
                new_ns = Namespace(part)
                ns.sub_namespaces[part] = new_ns
                ns = new_ns

    def get_namespace(self, name=None):
        if name == Namespace.SEP or not name:
            return self
        if name.startswith(Namespace.SEP):
            return self.get_namespace(name[1:])
        nodes = name.split(Namespace.SEP)
        if nodes[0] in self.sub_namespaces:
            return self.sub_namespaces[nodes[0]].get_namespace(
                Namespace.SEP.join(nodes[1:])
            )
        return None

    def get_leaves(self, recursive=False, prefix=""):
        if not recursive:
            return list(self.leaves)
        if self.name == Namespace.ROOT:
            prefix = ""
        else:
            prefix += self.name + Namespace.SEP

        leaves = []
        leaves.extend([prefix + x for x in self.leaves])
        for ns in self.sub_namespaces.values():
            leaves.extend(ns.get_leaves(True, prefix))
        return leaves
