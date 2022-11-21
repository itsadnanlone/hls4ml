import re

from hls4ml.model.layers import SymbolicExpression
from hls4ml.backends.template import LayerConfigTemplate, FunctionCallTemplate

from sympy.printing.cxx import CXX11CodePrinter
from sympy.core.numbers import Integer
from sympy.core import S

# Expression templates

expr_function_template = 'y[{y_index}] = {expr_str};'

expr_include_list = ['hls_math.h']

class HLSCodePrinter(CXX11CodePrinter):
    _ns = 'hls::'

    def __init__(self, layer, settings=None):
        super().__init__(settings)
        self.layer = layer

        for k in ('Abs Sqrt exp exp2 expm1 log log10 log2 log1p Cbrt hypot fma'
          ' loggamma sin cos tan asin acos atan atan2 sinh cosh tanh asinh acosh '
          'atanh erf erfc loggamma gamma ceiling floor').split():
            setattr(HLSCodePrinter, '_print_%s' % k, HLSCodePrinter._print_math)

    def _symbol_to_array(self, name):
        return re.sub(r'([a-zA-Z]+)(\d+)', r'\1[\2]', name)

    def _print_Float(self, flt):
        float_str = super()._print_Float(flt)
        return f'model_default_t({float_str})'

    def _print_Pow(self, expr):
        hls_type = self.layer.types['result_t']
        if isinstance(expr.exp, Integer):
            l_brac, r_brac = ('(', ')') if len(expr.base.args) > 1 else ('', '')
            if expr.exp > 1:
                return '(' + '*'.join([l_brac + self._symbol_to_array(self._print(expr.base)) + r_brac for _ in range(expr.exp)]) + ')'
            elif expr.exp == -1: # 1/x
                base = l_brac + self._symbol_to_array(self._print(expr.base)) + r_brac
                return f'hls::recip<{hls_type.precision.width}, {hls_type.precision.integer}>(({hls_type.name}){base})'
            else:
                return super()._print_Pow(expr)
        else:
            base = self._print(expr.base)
            if expr.exp == 0.5:
                return f'{self._ns}sqrt<{hls_type.precision.width}, {hls_type.precision.integer}>(({hls_type.name})({base}))'
            elif expr.exp == S.One/3:
                return f'{self._ns}cbrt<{hls_type.precision.width}, {hls_type.precision.integer}>(({hls_type.name})({base}))'
            else:
                exp = self._print(expr.exp)
                return f'{self._ns}pow<{hls_type.precision.width}, {hls_type.precision.integer}>(({hls_type.name})({base}), {exp})'

    def _print_math(self, expr):
        name = self.known_functions[expr.__class__.__name__]
        if not isinstance(name, str):
            for cb, fname in name:
                if cb(*expr.args):
                    name = fname
                    break
            else:
                raise ValueError("No matching printer")

        # Setting precision of math functions required some rethinking
        # Doing e.g., hls::pow<x.width, x.iwidth>(x, y) passes C sim, but fails synthesis, need to use hls::pow<16,6>(x,y)
        hls_type = self.layer.types['result_t']
        template = f'<{hls_type.precision.width}, {hls_type.precision.integer}>'
        cast = f'({hls_type.name})'
        args = ', '.join(map(lambda arg: self._print(arg), expr.args))

        return f'{self._ns}{name}{template}({cast}({args}))'

    def _print_Symbol(self, expr):
        name = super()._print_Symbol(expr)
        return self._symbol_to_array(name)

class ExpressionFunctionTemplate(FunctionCallTemplate):
    def __init__(self):
        super().__init__(SymbolicExpression, include_header=expr_include_list)
        self.template = expr_function_template
    
    def format(self, node):
        params = self._default_function_params(node)

        printer = HLSCodePrinter(node)

        fn_templates = []
        for i, expr in enumerate(node.attributes['expression']):
            params['expr_str'] = printer.doprint(expr)
            params['y_index'] = str(i)
            fn_templates.append(self.template.format(**params))

        return fn_templates
