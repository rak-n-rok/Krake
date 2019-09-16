def parse_stack_outputs(stack):
    return {output['output_key']: output['output_value']
            for output in stack['stack']['outputs']}


class FilterModule(object):

    def filters(self):
        return {
            'stack_outputs': parse_stack_outputs,
        }
