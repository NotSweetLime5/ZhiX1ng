import { Children, Fragment, isValidElement, type ButtonHTMLAttributes, type ReactNode } from 'react';
import * as SelectPrimitive from '@radix-ui/react-select';
import { clsx } from 'clsx';
import { Icon } from './Icon';

interface SelectProps extends Pick<ButtonHTMLAttributes<HTMLButtonElement>, 'id' | 'name' | 'className' | 'disabled' | 'aria-label' | 'aria-labelledby' | 'title'> {
  children: ReactNode;
  value?: string | number;
  defaultValue?: string | number;
  onValueChange?: (value: string) => void;
  required?: boolean;
}

interface Option { value: string; label: string; disabled?: boolean }
const EMPTY = '__zhixing_empty_selection__';
const encode = (value: string | number) => String(value) || EMPTY;

function textContent(children: ReactNode): string {
  return Children.toArray(children).map((child): string => {
    if (isValidElement<{ children?: ReactNode }>(child)) return textContent(child.props.children);
    return String(child);
  }).join('');
}

function readOptions(children: ReactNode): Option[] {
  const options: Option[] = [];
  Children.forEach(children, (child) => {
    if (!isValidElement<{ value?: string | number; children?: ReactNode; disabled?: boolean }>(child)) return;
    if (child.type === Fragment) options.push(...readOptions(child.props.children));
    if (child.type === 'option') {
      const label = textContent(child.props.children);
      options.push({ value: String(child.props.value ?? label), label, disabled: child.props.disabled });
    }
  });
  return options;
}

/** Shared themed select. Portals keep the menu clear of scrolling dialog boundaries. */
export function Select({ children, value, defaultValue, onValueChange, name, required, disabled, className, ...triggerProps }: SelectProps) {
  const options = readOptions(children);
  return (
    <SelectPrimitive.Root
      value={value === undefined ? undefined : encode(value)}
      defaultValue={defaultValue === undefined ? undefined : encode(defaultValue)}
      onValueChange={(next) => onValueChange?.(next === EMPTY ? '' : next)}
      name={name}
      required={required}
      disabled={disabled || options.length === 0}
    >
      <SelectPrimitive.Trigger className={clsx('field select-trigger', className)} {...triggerProps}>
        <span className="min-w-0 flex-1 truncate text-left"><SelectPrimitive.Value placeholder="请选择" /></span>
        <SelectPrimitive.Icon className="select-chevron"><Icon name="chevron" className="h-3.5 w-3.5 rotate-90" /></SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content className="select-menu" position="popper" sideOffset={6} collisionPadding={12} onEscapeKeyDown={(event) => event.stopPropagation()}>
          <SelectPrimitive.ScrollUpButton className="select-scroll"><Icon name="chevron" className="h-3.5 w-3.5 -rotate-90" /></SelectPrimitive.ScrollUpButton>
          <SelectPrimitive.Viewport className="p-1.5">
            {options.map((option) => (
              <SelectPrimitive.Item key={option.value} value={encode(option.value)} disabled={option.disabled} className="select-option" textValue={option.label}>
                <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
                <SelectPrimitive.ItemIndicator className="absolute right-3 flex items-center text-bone">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m5 12 4 4L19 6" /></svg>
                </SelectPrimitive.ItemIndicator>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
          <SelectPrimitive.ScrollDownButton className="select-scroll"><Icon name="chevron" className="h-3.5 w-3.5 rotate-90" /></SelectPrimitive.ScrollDownButton>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}
