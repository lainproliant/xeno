# Xeno: The Python dependency injector from outer space. 
[![Build Status](https://travis-ci.org/lainproliant/xeno.svg?branch=master)](https://travis-ci.org/lainproliant/xeno)

Xeno is a simple Python dependency injection framework. Use it when you
need to manage complex inter-object dependencies in a clean way. For the
merits of dependency injection and IOC, see
https://en.wikipedia.org/wiki/Dependency_injection.

Xeno should feel pretty familiar to users of Google Guice in Java, as it
is somewhat similar, although it is less focused on type names and more
on named resources and parameter injection.

# Installation

Installation is simple. With python3-pip, do the following:

```
$ sudo pip install -e .
```

Or, to install the latest version available on PyPI:

```
$ sudo pip install xeno
```

# Usage

To use Xeno as a dependency injection framework, you need to create a
xeno.Injector and provide it with modules. These modules are regular
Python objects with methods marked with the `@xeno.provider`
annotation. This annotation tells the `Injector` that this method
provides a named resource, the same name as the method marked with
`@provider`. These methods should either take no parameters (other
than `self`), or take named parameters which refer to other resources
by name, i.e. the providers can also be injected with other resources in
order to build a dependency chain.

Once you have an `Injector` full of resources, you can use it to
inject instances, functions, or methods with resources.

To create a new object instance by injecting resources into its
constructor, use `Injector.create(clazz)`, where `clazz` is the
class which you would like to instantiate. The constructor of this class
is called, and all named parameters in the constructor are treated as
resource references. Once the object is instantiated, any methods marked
with `@inject` are invoked with named resources provided.

Resources can be injected into normal functions, bound methods, or
existing object instances via `Injector.inject(obj)`. If the parameter
is an object instance, it is scanned for methods marked with `@inject`
and these methods are invoked with named resources provided.

## Example

In this simple example, we inject an output stream into an object.

```
import sys
from xeno import *

class OutputStreamModule:
   @provide
   def output_stream(self):
      return sys.stdout

class VersionWriter:
   def __init__(self, output_stream):
      self.output_stream = output_stream

   def write_version(self):
      print('The python version is %s' % sys.version_info,
            file=self.output_stream)

injector = Injector(OutputStreamModule())
writer = injector.create(VersionWriter)
writer.write_version()
```

Checkout `test.py` in the git repo for more usage examples.

## Change Log

### Version 4.10.0: Oct 28 2021
- Allow recipes to be specified with glob-style wildcards, as per `fnmatch`.

### Version 4.9.0: Jan 03 2021
- Deprecate `@recipe` factory decorator for `@factory`.
- Allow recipes to specify a `setup` recipe, which is not part
  of the recipe inputs or outputs but is needed to fulfill the task.

### Version 4.8.0: Dec 29 2020
- All recipe resources are loaded before targets are determined.
- Recipe names are now valid targets for a build.

### Version 4.7.0: Dec 16 2020
- Fixed a bug where build would continue resolving with outdated results.
- Added `@recipe` decorator to `xeno.build` to denote recipe functions.

### Version 4.4.0: Nov 2 2020
- Added experimental `xeno.build` module, a declarative build system driven by IOC.
- Added `xeno.color` offering basic ANSI color and terminal control.

### Version 4.3.0: May 9 2020
- Allow methods to be decorated with `@injector.provide`, eliminating the need for modules
  in some simple usage scenarios.

### Version 4.2.0: May 8 2020
- Split `Injector` into `AsyncInjector` and `SyncInjector` to allow injection to be performed
  in context of another event loop if async providers are not used.
- Fixed `AsyncInjector` to actually support asynchronous resolution of dependencies.

### Version 4.1.0: Feb 3 2020
- Added `Injector.get_ordered_dependencies` to get a breadth first list of
  dependencies in the order they are built.

### Version 4.0.0: May 12 2019
***BACKWARDS INCOMPATIBLE CHANGE***
- Removed support for parameter annotation aliases.  Use `@alias` on methods instead.
  This was removed to allow Xeno code to play nicely with PEP 484 type hinting.

### Version 3.1.0: August 29 2018
- Add ClassAttributes.for_object convenience method

### Version 3.0.0: May 4 2018
***BACKWARDS INCOMPATIBLE CHANGE***
- Provide injection interceptors with an alias map for the given param map.
- This change breaks all existing injection interceptors until the new param is added.

### Version 2.8.0: May 3 2018
- Allow decorated/wrapped methods to be properly injected if their `'params'` method attribute
  is carried forward.

### Version 2.7.0: April 20 2018
- The `Injector` now adds a `'resource-name'` attribute to resource methods allowing
  the inspection of a resource's full canonical name at runtime.

### Version 2.6.0: March 27 2018
- Bugfix release: Remove support for implicit asynchronous resolution of
  dependencies.  Providers can still be async, in order to await some other
  set of coroutines, but can no longer themselves be run in sync.  The
  benefits do not outweigh the complexity of bugs and timing concerns
  introduced by this approach.

### Version 2.5.0: March 2, 2018
- Added `Injector.provide_async()`.  Note that resource are always run within an
  event loop and should not use `inject()`, `provide()`, or `require()`
  directly, instead they should use `inject_async()`, `provide_async()`, and
  `require_async()` to dynamically modify resources.

### Version 2.4.1: January 30, 2018
- Added `Injector.scan_resources()` to allow users to scan for resource names with the given attributes.
- Added `Attributes.merge()` to assist with passing attributes down to functions which are wrapped in a decorator.
- Added `MethodAttributes.wraps()` static decorator to summarize a common use case of attribute merging.
- Added `MethodAttributes.add()` as a simple static decorator to add attribute values to a method's attributes.

### Version 2.4.0: January 21, 2018
- Dropped support for deprecated `Namespace.enumerate()` in favor of `Namespace.get_leaves()`.

### Version 2.3.0: January 21, 2018
- Added support for asyncio-based concurrency and async provider coroutines with per-injector event loops (`injector.loop`).

### Version 2.2.0: September 19, 2017
- Expose the Injector's Namespace object via `Injector.get_namespace()`.  This is useful for users who want to list the contents of namespaces.

### Version 2.1.0: August 23rd, 2017
- Allow multiple resource names to be provided to `Injector.get_dependency_graph()`.

### Version 2.0.0: July 25th, 2017
***BACKWARDS INCOMPATIBLE CHANGE***
- Change the default namespace separator and breakout symbol to '/'

Code using the old namespace separator can be made to work by overriding the value of xeno.Namespace.SEP:
```
import xeno
xeno.Namespace.SEP = '::'
```

### Version 1.10: July 25th, 2017
- Allow names prefixed with `::` to escape their module's namespace, e.g. `::top_level_item`

### Version 1.9: May 23rd, 2017
- Add `@const()` module annotation for value-based resources
- Add `Injector.get_dependency_tree()` to fetch a tree of dependency names for a given resource name.

### Version 1.8: May 16th, 2017
- Add `MissingResourceError` and `MissingDependencyError` exception types.

### Version 1.7: May 16th, 2017
- Major update, adding support for namespaces, aliases, and inline resource parameter aliases.  See the unit tests in test.py for examples.
  - Added `@namespace('Name')` decorator for modules to specify that all resources defined in the module should be scoped within 'Name::'.
  - Added `@name('alt-name')` to allow resources to be named something other than the name of the function that defines them.
  - Added `@alias('alt-name', 'name')` to allow a resource to be renamed within either the scope of a single resource or a whole module.
  - Added `@using('NamespaceName')` to allow the contents of the given namespace
    to be automatically aliases into either the scope of a single resource or
    a whole module.
  - Added support for resource function annotations via PEP 3107 to allow
    inline aliases, e.g. `def my_resource(name: 'Name::something-important'):`

### Version 1.6: April 26th, 2017
- Changed how `xeno.MethodAttributes` works: it now holds a map of attributes
  and provides methods `get()`, `put()`, and `check()`

### Version 1.5: April 26th, 2017
- Added injection interceptors
- Refactored method tagging to use `xeno.MethodAttributes` instead of named
  object attributes to make attribute tagging more flexible and usable by
  the outside world, e.g. for the new injectors.

### Version 1.4: August 30th, 2016
- Added cycle detection.

### Version 1.3: August 29th, 2016
- Have the injector offer itself as a named resource named 'injector'.

