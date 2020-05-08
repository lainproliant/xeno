# --------------------------------------------------------------------
# errors.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday May 7, 2020
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------


# --------------------------------------------------------------------
class InjectionError(Exception):
    pass


# --------------------------------------------------------------------
class MissingResourceError(InjectionError):
    def __init__(self, name):
        super().__init__('The resource "%s" was not provided.' % name)
        self.name = name


# --------------------------------------------------------------------
class MissingDependencyError(InjectionError):
    def __init__(self, name, dep_name):
        super().__init__(
            f'Resource "{dep_name}" required by "{name}" was not provided.')
        self.name = name
        self.dep_name = dep_name


# --------------------------------------------------------------------
class MethodInjectionError(InjectionError):
    def __init__(self, method, name, reason=None):
        super().__init__(
            f'Failed to inject "{name}" into {method.__qualname__}'
            + f': {reason}' if reason else '.'
        )
        self.method = method
        self.name = name


# --------------------------------------------------------------------
class ClassInjectionError(InjectionError):
    def __init__(self, class_, name, reason=None):
        super().__init__(
            'Failed to inject "%s" into constructor for class "%s".'
            % (name, class_.__qualname__)
            + reason
            or ""
        )
        self.class_ = class_
        self.name = name


# --------------------------------------------------------------------
class CircularDependencyError(InjectionError):
    def __init__(self, resource, dep):
        super().__init__(
            'Circular dependency detected between "%s" and "%s".' % (
                resource, dep)
        )
        self.resource = resource
        self.dep = dep


# --------------------------------------------------------------------
class UndefinedNameError(InjectionError):
    def __init__(self, name):
        super().__init__('Undefined name: "%s"' % name)
        self.name = name


# --------------------------------------------------------------------
class UnknownNamespaceError(InjectionError):
    def __init__(self, name):
        super().__init__('Unknown namespace: "%s"' % name)
        self.name = name


# --------------------------------------------------------------------
class InvalidResourceError(InjectionError):
    pass
