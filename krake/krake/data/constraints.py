from krake.data.core import validate_value, validate_key
from lark import Lark, UnexpectedInput
from marshmallow import ValidationError, fields
from marshmallow.utils import ensure_text_type


class LabelConstraint(object):
    """A label constraint is used to filter :class:`.serializable.ApiObject`
    based on their labels.

    A very simple language for expressing label constraints is used. The
    following operations can be expressed:

    equality
        The value of a label must be equal to a specific value::

            <label> is <value>
            <label> = <value>
            <label> == <value>

    non-equality
        The value of a label must not be equal to a specific value::

            <label> is not <value>
            <label> != <value>

    inclusion
        The value of a label must be inside a set of values::

            <label> in (<value>, <value>, ...)

    exclusion
        The value of a label must not be inside a set of values::

            <label> not in (<value>, <value>, ...)

    Args:
        parsed (str, optional): Parsed string expression.

    Example:
        .. code:: python

            labels = {
                "location": "IT"
            }

            constraint = LabelConstraint.parse("location in (DE, UK)")
            constraint.match(labels)  # returns False

    """

    grammar = Lark(
        """
        start: key (equal | notequal | in | notin)

        // Accept any kind of string, no validation is performed on the key here
        key: /[^ ,()=!]+/

        // Accept any kind of string, no validation is performed on the value here
        value: /[^ ,()=!]+/

        equal: ("==" | "=" | "is") value

        notequal: ("!=" | "is" "not") value

        in: "in" "(" (value ",")* value ","* ")"

        notin: "not" "in" "(" (value ",")* value ","* ")"

        %ignore " "
        %ignore "\t"
        """
    )

    def __init__(self, parsed=None):
        self.parsed = parsed

    def __eq__(self, other):
        if isinstance(other, LabelConstraint):
            # If other is also a label constraint but from a different
            # subclass, the constraints are not equal.
            if not isinstance(other, self.__class__):
                return False
        else:
            # Comparison with other types is not implemented
            return NotImplemented

        return self._as_tuple() == other._as_tuple()

    def __hash__(self, other):
        return hash(self._as_tuple())

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.__str__()}>"

    def expression(self):
        """Returns an expression representing the constraint.

        Returns:
            str: String expression of the constraint

        """
        raise NotImplementedError()

    @classmethod
    def parse(cls, expression):
        """Parse a constraint expression into its Python representation.

        Args:
            expression (str): Constraint expression

        Returns:
            LabelConstraint: An instance of the constraint class representing
            the parsed expression.

        """
        tree = cls.grammar.parse(expression)
        label = tree.children[0].children[0]
        validate_key(label)
        operation = tree.children[1].data

        def format_possibilities(token):
            """Format one token to extract the actual value inside.
            """
            single_value = str(token.children[0])
            validate_value(single_value)
            return single_value

        if operation == "equal":
            value = str(tree.children[1].children[0].children[0])
            validate_value(value)
            return EqualConstraint(label, value, parsed=expression)

        elif operation == "notequal":
            value = str(tree.children[1].children[0].children[0])
            validate_value(value)
            return NotEqualConstraint(label, value, parsed=expression)

        elif operation == "in":
            values = map(format_possibilities, tree.children[1].children)
            return InConstraint(label, values, parsed=expression)

        elif operation == "notin":
            values = map(format_possibilities, tree.children[1].children)
            return NotInConstraint(label, values, parsed=expression)

        else:
            raise ValueError(f"Unknown operation {operation!r}")

    def match(self, labels):
        """Match the constraint against a set label mapping.

        Args:
            labels (dict): Mapping of labels

        Returns:
            bool: :data:`True` of the passed labels fulfill the constraint,
            otherwise :data:`False`.

        """
        raise NotImplementedError()

    def _as_tuple(self):
        """Returns a tuple representation of the constraint.

        This tuple is used by the :meth:`__eq__` and :meth:`__hash__` methods.
        This makes constraints hashable and comparable across each other.

        Returns:
            tuple: Tuple representing the constraint
        """
        raise NotImplementedError()

    class Field(fields.Field):
        """Serializer for :class:`LabelConstraint`.

        Constraints are represented as string expressions. This field parses
        the expressions on deserialization and returns the string
        representation on serialization.
        """

        def _deserialize(self, value, attr, obj, **kwargs):
            if value is None:
                return None

            expression = ensure_text_type(value)
            try:
                return LabelConstraint.parse(expression)
            except UnexpectedInput:
                raise ValidationError("Invalid label constraint")

        def _serialize(self, value, attr, data, **kwargs):
            if not isinstance(value, LabelConstraint):
                raise self.make_error("invalid")

            if value.parsed is None:
                return str(value)

            try:
                return ensure_text_type(value.parsed)
            except UnicodeDecodeError as error:
                raise self.make_error("invalid_utf8") from error


class EqualConstraint(LabelConstraint):
    """Label constraint where the value of a label needs to match a specific
    value.

    Example:
        .. code:: python

            # The following constraints are equivalent
            LabelConstraint.parse("location is EU")
            LabelConstraint.parse("location = EU")
            LabelConstraint.parse("location == EU")

    """

    def __init__(self, label, value, parsed=None):
        super().__init__(parsed)
        self.label = label
        self.value = value

    def __str__(self):
        return f"{self.label} is {self.value}"

    def _as_tuple(self):
        return (self.label, self.value)

    def match(self, labels):
        try:
            return labels[self.label] == self.value
        except KeyError:
            return False


class NotEqualConstraint(EqualConstraint):
    """Label constraint where the value of a label must not match a specific
    value.

    Example:
        .. code:: python

            # The following constraints are equivalent
            LabelConstraint.parse("location is not UK")
            LabelConstraint.parse("location != UK")

    """

    def __str__(self):
        return f"{self.label} is not {self.value}"

    def match(self, labels):
        try:
            return labels[self.label] != self.value
        except KeyError:
            return False


class InConstraint(LabelConstraint):
    """Label constraint where the value of a label must be in a set of
    values.

    Example:
        .. code:: python

            LabelConstraint.parse("location in (DE, SK)")

    """

    def __init__(self, label, values, parsed=None):
        super().__init__(parsed)
        self.label = label
        self.values = tuple(values)

    def __str__(self):
        return f"{self.label} in ({', '.join(self.values)})"

    def _as_tuple(self):
        return (self.label, self.values)

    def match(self, labels):
        try:
            return labels[self.label] in self.values
        except KeyError:
            return False


class NotInConstraint(InConstraint):
    """Label constraint where the value of a label must not be in a set of
    values.

    Example:
        .. code:: python

            LabelConstraint.parse("location not in (DE, SK)")

    """

    def __str__(self):
        return f"{self.label} not in ({', '.join(self.values)})"

    def match(self, labels):
        try:
            return labels[self.label] not in self.values
        except KeyError:
            return False
