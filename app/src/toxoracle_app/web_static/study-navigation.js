'use strict';
// Viewing history never changes execution state or grants approval.
class StudyNavigation {
  constructor(){this.reset();}
  reset(){this.latest='input';this.reached=0;this.selected=null;}
  get order(){return ['input','review','run','assess','results'];}
  advance(name){this.latest=name;this.reached=Math.max(this.reached,this.order.indexOf(name));}
  select(name){if(this.order.indexOf(name)<0||this.order.indexOf(name)>this.reached)return false;this.selected=name;return true;}
  get viewing(){return this.selected || this.latest;}
  follow(){this.selected=null;}
}
