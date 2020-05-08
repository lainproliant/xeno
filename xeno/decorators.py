# --------------------------------------------------------------------
# decorators.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday May 7, 2020
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import inspect

from .attributes import ClassAttributes, MethodAttributes


# --------------------------------------------------------------------
def singleton(f):
    """
    Method annotation indicating a named singleton resource.

    The function will only ever be invoked on an instance of the
    module once, and the return value will be provided to all
    injected objects that require it.
    """

    attrs = MethodAttributes.for_method(f, write=True)
    attrs.put("singleton")
    attrs.put("provider")
    return f


# --------------------------------------------------------------------
def provide(f):
    """
    Method annotation indicating a named resource.

    The function will be added to the Injector's resource map and
    called each time an injected instance is created that requires
    the resource.
    """

    attrs = MethodAttributes.for_method(f, write=True)
    attrs.put("provider")
    return f


# --------------------------------------------------------------------
def inject(f):
    """
    Method annotation indicating an injection point in an object.

    Instance methods marked with @inject are called after an object
    is created via Injector.create() or if an instance is passed
    to Injector.inject().

    All of the parameters of a method marked with @inject must refer
    to named resources in the Injector, or must provide default values
    which can be overridden by resources in the injector.
    """
    attrs = MethodAttributes.for_method(f, write=True)
    attrs.put("injection-point")
    return f


# --------------------------------------------------------------------
def named(name):
    """
    Method annotation indicating a name for the given resource other
    than the name of the method itself.
    """

    def impl(f):
        attrs = MethodAttributes.for_method(f, write=True)
        attrs.put("name", name)
        return f

    return impl


# --------------------------------------------------------------------
def alias(alias, name):
    """
    Aliases a single resource to a different name in the given
    module or resource context.
    """

    def impl(obj):
        attrs = None
        if inspect.isclass(obj):
            attrs = ClassAttributes.for_class(obj, write=True)
        else:
            attrs = MethodAttributes.for_method(obj, write=True)
        aliases = attrs.get("aliases", {})
        aliases[alias] = name
        attrs.put("aliases", aliases)
        return obj

    return impl


# --------------------------------------------------------------------
def namespace(name):
    """
    Module annotation indicating that the resources defined inside
    should be scoped into the given namespace, that is the given
    string is appended to all resource names followed by '/'.
    """

    def impl(class_):
        attrs = ClassAttributes.for_class(class_, write=True)
        attrs.put("namespace", name)
        return class_

    return impl


# --------------------------------------------------------------------
def const(name, value):
    """
    Module annotation defining a constant resource scoped into the
    module's namespace.
    """

    def impl(class_):
        attrs = ClassAttributes.for_class(class_, write=True)
        const_map = attrs.get("const_map", {})
        const_map[name] = value
        attrs.put("const_map", const_map)
        return class_

    return impl


# --------------------------------------------------------------------
def using(name):
    def impl(obj):
        attrs = None
        if inspect.isclass(obj):
            attrs = ClassAttributes.for_class(obj, write=True)
        else:
            attrs = MethodAttributes.for_method(obj, write=True)
        namespaces = attrs.get("using-namespaces", [])
        namespaces.append(name)
        attrs.put("using-namespaces", namespaces)
        return obj

    return impl
