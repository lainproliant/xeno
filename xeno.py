#--------------------------------------------------------------------
# Xeno: The Python dependency injector from outer space.
#
# Author: Lain Supe (lainproliant)
# Date: Sunday, August 28th 2016
#
# Released under a 3-clause BSD license, see LICENSE for more info.
#--------------------------------------------------------------------
import collections
import inspect

#--------------------------------------------------------------------
class InjectionError(Exception):
    pass

#--------------------------------------------------------------------
class MethodInjectionError(InjectionError):
    def __init__(self, method, name, reason = None):
        super().__init__('Failed to inject "%s" into method "%s".' % (
            name,
            method.__qualname__) + reason or "")
        self.method = method
        self.name = name

#--------------------------------------------------------------------
class ClassInjectionError(InjectionError):
    def __init__(self, clazz, name, reason = None):
        super().__init__('Failed to inject "%s" into constructor for class "%s".' % (
            name,
            clazz.__qualname__) + reason or "")
        self.clazz = clazz
        self.name = name

#--------------------------------------------------------------------
class CircularDependencyError(InjectionError):
    def __init__(self, resource, dep):
        super().__init__('Circular dependency detected between "%s" and "%s".' % (
            resource, dep))
        self.resource = resource
        self.dep = dep

#--------------------------------------------------------------------
class MethodAttributes:
    @staticmethod
    def for_method(f, create = True, write = False, ctor = False):
        try:
            return f._xeno_method_attrs
        except AttributeError:
            if create:
                attrs = MethodAttributes(f, ctor = ctor)
                if write:
                    f._xeno_method_attrs = attrs
                return attrs
            else:
                return None

    def put(self, attr, value = True):
        self.attr_map[attr] = value
        return self

    def get(self, attr, default_value = None, throw_if_missing = True):
        if attr in self.attr_map:
            return self.attr_map[attr]
        elif throw_if_missing and default_value is None:
            raise AttributeError('No such method attribute: %s' % attr)
        else:
            return default_value

    def check(self, attr):
        return True if self.get(attr, throw_if_missing = False) else False

    def __init__(self, f, ctor):
        self.attr_map = {}
        self.put('name', f.__name__)
        self.put('qualname', f.__qualname__)

#--------------------------------------------------------------------
def singleton(f):
    """
    Method annotation indicating a named singleton resource.

    The function will only ever be invoked on an instance of the
    module once, and the return value will be provided to all
    injected objects that require it.
    """

    attrs = MethodAttributes.for_method(f, write = True)
    attrs.put('singleton')
    attrs.put('provider')
    return f

#--------------------------------------------------------------------
def provide(f):
    """
    Method annotation indicating a named resource.

    The function will be added to the Injector's resource map and
    called each time an injected instance is created that requires
    the resource.
    """

    attrs = MethodAttributes.for_method(f, write = True)
    attrs.put('provider')
    return f

#--------------------------------------------------------------------
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
    attrs = MethodAttributes.for_method(f, write = True)
    attrs.put('injection_point')
    return f

#--------------------------------------------------------------------
def bind_unbound_method(obj, method):
    return method.__get__(obj, obj.__class__)

#--------------------------------------------------------------------
def scan_methods(obj, filter_f):
    """
    Scan the object for methods that match the given attribute filter
    and return them as a stream of tuples.
    """
    for clazz in inspect.getmro(obj.__class__):
        for name, method in inspect.getmembers(clazz, predicate = inspect.isfunction):
            attrs = MethodAttributes.for_method(method, create = False)
            if attrs is not None and filter_f(attrs):
                yield (attrs, bind_unbound_method(obj, method))

#--------------------------------------------------------------------
def get_injection_points(obj):
    """
    Scan the object and all of its parents for injection points
    and return them as a stream of tuples.
    """

    return scan_methods(obj, lambda attr: attr.check('injection_point'))

#--------------------------------------------------------------------
def get_providers(obj):
    """
    Scan the object and all of its parents for providers and return
    them as a stream of tuples.
    """

    return scan_methods(obj, lambda attr: attr.check('provider'))

#--------------------------------------------------------------------
def get_injection_params(f, unbound_ctor = False):
    """
    Fetches the injectable parameter names of parameters to the given
    method, along with a set of parameters which have default values
    and should be considered optional dependencies.

    This method will throw InjectionError if the method provided has
    arguments that are not POSITIONAL_OR_KEYWORD or KEYWORD_ONLY.

    If the method provided is an unbound object constructor,
    unbound_ctor must be set to True to prevent 'self' from being
    returned by this method as an injectable parameter.
    """
    sig = inspect.signature(f)
    injection_param_names = []
    default_param_set = set()
    params = list(sig.parameters.values())

    if not inspect.ismethod(f) and unbound_ctor:
        if not inspect.isfunction(f):
            # We do not want to try to inject a slot wrapper
            # version of __init__, as its params are (*args, **kwargs)
            # and it does nothing anyway.
            return [], set()

        else:
            # Don't try to inject the 'self' parameter of an
            # unbound constructor.
            params = params[1:]

    for param in params:
        if param.kind in [inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY]:
            if param.default != param.empty:
                default_param_set.add(param.name)
            injection_param_names.append(param.name)
        else:
            raise InjectionError('xeno only supports injection of POSITIONAL_OR_KEYWORD and KEYWORD_ONLY arguments, %s arguments (%s) are not supported.' % (
                param.kind, param.name))
    return injection_param_names, default_param_set

#--------------------------------------------------------------------
class Injector:
    """
    An object responsible for collecting resources from modules and
    injecting them into newly created instances.

    An Injector is instantianted with any number of modules, which
    provide resources via methods annotated with @provide.  These
    methods are allowed to depend on other resources, potentially
    from myriad other modules, in order to generate their
    dependencies.

    Evaulation and injection of dependencies is lazy, meaning that
    the dependency graph is not evaluated until a resource is
    requested.
    """
    def __init__(self, *modules):
        """
        Create an Injector object.

        *modules: A list of modules to include in the injector.
                  More modules can be added later by calling
                  Injector.add_module().
        """
        self.resources = {'injector': lambda: self}
        self.singletons = {}
        self.dep_graph = {}
        self.injection_interceptors = []

        for module in modules:
            self.add_module(module, skip_cycle_check = True)
        self._check_for_cycles()

    def add_module(self, module, skip_cycle_check = False):
        """
        Add a module to the injector.  The module is scanned for @provider
        annotated methods, and these methods are added as resources to
        the injector.
        """
        for attrs, provider in get_providers(module):
            self._bind_resource(attrs.get('name'), provider)

        if not skip_cycle_check:
            self._check_for_cycles()

    def add_injection_interceptor(self, interceptor):
        """
        Specifies a function to be called before resources are injected into
        a provider, constructor, or injection point.  Resources are provided
        to the function as a key/value map.

        The injection interceptor is expected to return a key/value map
        containing all of the resources provided to it, either modified
        or in their original form.  Failure to provide all required
        resources will lead to an InjectionError after the interceptors
        are invoked.
        """
        self.injection_interceptors.append(interceptor)

    def create(self, clazz):
        """
        Create an instance of the specified class.  The class' constructor
        must follow the rules for @inject methods, such that all of its
        parameters refer to injectable resources or are optional.

        If the object needs to be constructed with objects not from the
        Injector, do not use this method.  Instead, instantiate the object
        with these parameters in the constructor, then mark one or more
        methods with @inject and pass the instance to Injector.inject().
        """
        try:
            dependency_map = self._resolve_dependencies(clazz.__init__, unbound_ctor = True)
            attrs = MethodAttributes.for_method(clazz.__init__, ctor = True)
            dependency_map = self._invoke_injection_interceptors(attrs, dependency_map)
        except MethodInjectionError as e:
            raise ClassInjectionError(clazz, e.name)

        instance = clazz(**dependency_map)
        self._inject_instance(instance)
        return instance

    def inject(self, obj):
        """
        Inject a method or object instance with resources from this Injector.

        obj: A method or object instance.  If this is a method, all named
             parameters are injected from the Injector.  If this is an instance,
             its methods are scanned for injection points and these methods
             are all invoked with resources from the Injector.
        """
        if inspect.isfunction(obj) or inspect.ismethod(obj):
            return self._inject_method(obj)
        else:
            return self._inject_instance(obj)

    def require(self, name, method = None):
        """
        Require a named resource from this Injector.  If it can't be provided,
        an InjectionError is raised.

        Optionally, a method can be specified.  This indicates the method that
        requires the resource for injection, and causes this method to throw
        MethodInjectionError instead of InjectionError if hte resource was
        not provided.
        """
        if not name in self.resources:
            if method is not None:
                raise MethodInjectionError(method, name, 'Resource was not provided.')
            else:
                raise InjectionError('The required resource "%s" was not provided.' % name)
        else:
            return self.resources[name]()

    def has(self, name):
        """
        Determine if this Injector has been provided with the named resource.
        """
        return name in self.resources

    def _bind_resource(self, name, bound_method):
        params, _ = get_injection_params(bound_method)
        attrs = MethodAttributes.for_method(bound_method)
        injected_method = self.inject(bound_method)
        if attrs.check('singleton'):
            def wrapper():
                if not name in self.singletons:
                    singleton = injected_method()
                    self.singletons[name] = singleton
                    return singleton
                else:
                    return self.singletons[name]
            resource = wrapper
        else:
            resource = injected_method

        self.resources[name] = resource
        self.dep_graph[name] = params

    def _check_for_cycles(self):
        visited = set()

        def visit(resource):
            visited.add(resource)
            for dep in self.dep_graph.get(resource, ()):
                if dep in visited or visit(dep):
                    raise CircularDependencyError(resource, dep)
            visited.remove(resource)

        for resource in self.dep_graph.keys():
            visit(resource)

    def _resolve_dependencies(self, f, unbound_ctor = False):
        params, default_set = get_injection_params(f, unbound_ctor = unbound_ctor)
        dependency_map = {}
        for param in params:
            if param in default_set and not self.has(param):
                continue
            dependency_map[param] = self.require(param)
        return dependency_map

    def _inject_instance(self, instance):
        for attrs, injection_point in get_injection_points(instance):
            self.inject(injection_point)()
        return instance

    def _inject_method(self, method):
        def wrapper():
            dependency_map = self._resolve_dependencies(method)
            attrs = MethodAttributes.for_method(method)
            depencency_map = self._invoke_injection_interceptors(attrs, dependency_map)
            return method(**dependency_map)
        return wrapper

    def _invoke_injection_interceptors(self, attrs, dependency_map):
        for interceptor in self.injection_interceptors:
            dependency_map = interceptor(attrs, dependency_map)
        return dependency_map

