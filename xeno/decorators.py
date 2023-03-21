# --------------------------------------------------------------------
# decorators.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday May 7, 2020
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import inspect

from .attributes import ClassAttributes, MethodAttributes, Tags

# --------------------------------------------------------------------
def singleton(f):
    """
    Method annotation indicating a named singleton resource.

    The function will only ever be invoked on an instance of the
    module once, and the return value will be provided to all
    injected objects that require it.
    """

    attrs = MethodAttributes.for_method(f, write=True)
    assert attrs is not None
    attrs.put(Tags.SINGLETON)
    attrs.put(Tags.PROVIDER)
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
    assert attrs is not None
    attrs.put(Tags.PROVIDER)
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
    assert attrs is not None
    attrs.put(Tags.INJECTION_POINT)
    return f


# --------------------------------------------------------------------
def named(name):
    """
    Method annotation indicating a name for the given resource other
    than the name of the method itself.
    """

    def impl(f):
        attrs = MethodAttributes.for_method(f, write=True)
        assert attrs is not None
        attrs.put(Tags.NAME, name)
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
        assert attrs is not None
        aliases = attrs.get(Tags.ALIASES, {})
        aliases[alias] = name
        attrs.put(Tags.ALIASES, aliases)
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
        assert attrs is not None
        attrs.put(Tags.NAMESPACE, name)
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
        assert attrs is not None
        const_map = attrs.get(Tags.CONST_MAP, {})
        const_map[name] = value
        attrs.put(Tags.CONST_MAP, const_map)
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
        assert attrs is not None
        namespaces = attrs.get(Tags.USING_NAMESPACES, [])
        namespaces.append(name)
        attrs.put(Tags.USING_NAMESPACES, namespaces)
        return obj

    return impl
