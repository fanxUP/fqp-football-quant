import { describe, expect, it } from 'vitest';
import { MODEL_ORDER, getModelLineVisual } from './modelVisuals';

describe('getModelLineVisual', () => {
  it('为全部预测模型提供互不相同的稳定折线颜色', () => {
    const firstPass = MODEL_ORDER.map((modelName) => getModelLineVisual(modelName).color);
    const secondPass = MODEL_ORDER.map((modelName) => getModelLineVisual(modelName).color);

    expect(MODEL_ORDER).toHaveLength(19);
    expect(new Set(firstPass).size).toBe(MODEL_ORDER.length);
    expect(secondPass).toEqual(firstPass);
  });

  it('未知模型也按名称稳定分配颜色', () => {
    expect(getModelLineVisual('future_model')).toEqual(getModelLineVisual('future_model'));
  });
});
